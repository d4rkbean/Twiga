"""Display preferences: interface variant, theme and density.

Same mechanism as the language (backend/i18n.py): the account setting wins,
then the cookie (authentication disabled, or the login page), then the
default. The values of the current request live in ContextVars set by
LocaleMiddleware, so templates read them without any parameter passing.
"""

from __future__ import annotations

import os
from contextvars import ContextVar

UI_VARIANTS = ("classic", "other_way")
THEMES = ("light", "system", "dark")
DENSITIES = ("compact", "normal", "comfortable")

DEFAULT_UI_VARIANT = "classic"
DEFAULT_THEME = "system"
DEFAULT_DENSITY = "normal"

UI_COOKIE = "twiga_ui"
THEME_COOKIE = "twiga_theme"
DENSITY_COOKIE = "twiga_density"

_current_ui_variant: ContextVar[str] = ContextVar("twiga_ui_variant", default=DEFAULT_UI_VARIANT)
_current_theme: ContextVar[str] = ContextVar("twiga_theme", default=DEFAULT_THEME)
_current_density: ContextVar[str] = ContextVar("twiga_density", default=DEFAULT_DENSITY)


def other_way_enabled() -> bool:
    # "The other way" is not built yet (lot 4): the choice is offered, disabled,
    # until ENABLE_OTHER_WAY is set. Read at call time so a test can toggle it.
    return os.environ.get("ENABLE_OTHER_WAY", "false").strip().lower() in ("1", "true", "yes", "on")


def valid_ui_variants() -> tuple[str, ...]:
    return UI_VARIANTS if other_way_enabled() else ("classic",)


def _pick(user, attribute: str, cookies: dict[str, str], cookie_name: str, allowed, default: str) -> str:
    value = getattr(user, attribute, None) if user is not None else None
    if value not in allowed:
        value = cookies.get(cookie_name)
    if value not in allowed:
        value = default
    return value


def resolve(user, cookies: dict[str, str]) -> tuple[str, str, str]:
    """Return (ui_variant, theme, density): account, then cookie, then default."""
    ui_variant = _pick(user, "ui_variant", cookies, UI_COOKIE, UI_VARIANTS, DEFAULT_UI_VARIANT)
    if ui_variant == "other_way" and not other_way_enabled():
        ui_variant = DEFAULT_UI_VARIANT
    theme = _pick(user, "theme", cookies, THEME_COOKIE, THEMES, DEFAULT_THEME)
    density = _pick(user, "density", cookies, DENSITY_COOKIE, DENSITIES, DEFAULT_DENSITY)
    return ui_variant, theme, density


def set_current(ui_variant: str, theme: str, density: str) -> None:
    _current_ui_variant.set(ui_variant)
    _current_theme.set(theme)
    _current_density.set(density)


def current_ui_variant() -> str:
    return _current_ui_variant.get()


def current_theme() -> str:
    return _current_theme.get()


def current_density() -> str:
    return _current_density.get()
