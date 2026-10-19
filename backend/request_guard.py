"""Requests sent by another site, and requests for an unknown host name.

Cross-site requests: a page on another site can make the browser of a Twiga
user send a form to Twiga (the session cookie goes with it on a top-level
POST, and nothing at all is needed when authentication is off). Browsers add
an `Origin` header (or at least a `Referer`) to those requests: every unsafe
request (POST, PUT, PATCH, DELETE) whose origin is not Twiga itself is refused.
A request with neither header (curl, scripts) is let through: it does not come
from a browser page, so it cannot carry someone else's cookie.

Twiga itself means the `Host` header of the request, or `X-Forwarded-Host`
when a reverse proxy sets it (a page of another site cannot add that header to
a request), or one of the origins listed in TRUSTED_ORIGINS.

Unknown host names: with ALLOWED_HOSTS set, a request for any other host name
is refused (protection against DNS rebinding). Empty, every host is accepted,
as before.
"""

from __future__ import annotations

import logging
import os
from urllib.parse import urlsplit

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from backend import i18n
from backend.i18n import gettext as _t

logger = logging.getLogger("twiga.security")

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}
_DEFAULT_PORTS = {"http": "80", "https": "443"}
# Always answered, whatever the host name: a health check has nothing to protect.
_HOST_CHECK_EXEMPT_PATHS = {"/health"}


def _split_list(value: str | None) -> list[str]:
    return [item.strip().lower().rstrip("/") for item in (value or "").split(",") if item.strip()]


def _hostname(netloc: str) -> str:
    """The host name without its port ("[::1]:8181" -> "[::1]")."""
    if netloc.startswith("["):
        return netloc.split("]")[0] + "]"
    return netloc.split(":")[0]


def _strip_default_port(netloc: str, scheme: str | None = None) -> str:
    """"host:443" -> "host" for https (any default port when the scheme is unknown)."""
    hostname = _hostname(netloc)
    port = netloc[len(hostname) + 1 :]
    default_ports = [_DEFAULT_PORTS[scheme]] if scheme in _DEFAULT_PORTS else _DEFAULT_PORTS.values()
    return hostname if port in default_ports else netloc


TRUSTED_ORIGINS = _split_list(os.environ.get("TRUSTED_ORIGINS"))
ALLOWED_HOSTS = _split_list(os.environ.get("ALLOWED_HOSTS"))


def _source_of(request: Request) -> str | None:
    """The origin a browser declared for this request ("https://host:port"), or None."""
    origin = request.headers.get("origin")
    if origin is not None:
        return origin.strip().lower()
    referer = request.headers.get("referer")
    if referer:
        parts = urlsplit(referer.strip().lower())
        return f"{parts.scheme}://{parts.netloc}"
    return None


def is_same_origin(request: Request, source: str) -> bool:
    parts = urlsplit(source)
    if not parts.scheme or not parts.netloc:
        return False  # "null" (sandboxed page, privacy redirect) or garbage
    if source in TRUSTED_ORIGINS:
        return True
    netloc = _strip_default_port(parts.netloc, parts.scheme)
    candidates = [request.headers.get("host", "")]
    forwarded_host = request.headers.get("x-forwarded-host")
    if forwarded_host:
        candidates.append(forwarded_host.split(",")[0])
    return any(netloc == _strip_default_port(candidate.strip().lower()) for candidate in candidates if candidate)


def is_allowed_host(request: Request) -> bool:
    if not ALLOWED_HOSTS:
        return True
    host = request.headers.get("host", "").strip().lower()
    return host in ALLOWED_HOSTS or _hostname(host) in ALLOWED_HOSTS


class RequestGuardMiddleware(BaseHTTPMiddleware):
    # Applies with and without authentication: with AUTH_ENABLED=false nobody
    # needs to be signed in for a forged form to change the data.
    async def dispatch(self, request: Request, call_next):
        # Runs before LocaleMiddleware: the language of a refusal comes from the cookie.
        i18n.set_locale(*i18n.resolve_locale(None, request.cookies))
        if request.url.path not in _HOST_CHECK_EXEMPT_PATHS and not is_allowed_host(request):
            logger.warning("Refused a request for host %r (not in ALLOWED_HOSTS)", request.headers.get("host"))
            return Response(_t("Adresse du serveur non autorisée."), status_code=400, media_type="text/plain")

        if request.method not in _SAFE_METHODS:
            source = _source_of(request)
            if source is not None and not is_same_origin(request, source):
                logger.warning(
                    "Refused a %s %s sent from %r to host %r: if Twiga is reached at that address, add it to TRUSTED_ORIGINS",
                    request.method,
                    request.url.path,
                    source,
                    request.headers.get("host"),
                )
                return Response(
                    _t("Requête refusée : elle ne vient pas de Twiga."), status_code=403, media_type="text/plain"
                )
        return await call_next(request)
