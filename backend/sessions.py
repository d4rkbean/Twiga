"""Open sessions of an account: the list shown in "Mon profil", closing them, and the
readable description of the device taken from the User-Agent.

The signing and checking of the cookie live in backend/auth.py; this module is only the
table of sessions (models.UserSession) and what the interface shows of it.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.formatting import format_date
from backend.i18n import gettext as _t
from backend.i18n import ngettext
from backend.models import UserSession

# A session lives as long as its cookie (see auth.SESSION_MAX_AGE).
SESSION_LIFETIME = timedelta(days=30)
# Last activity is written at most once per minute: no write on every request.
TOUCH_INTERVAL = timedelta(seconds=60)


def describe_user_agent(user_agent: str | None) -> tuple[str, str]:
    """(device, browser) in plain words, from a User-Agent header."""
    ua = user_agent or ""
    # Order matters: an iPhone says "like Mac OS X" and an Android phone says "Linux".
    if "iPhone" in ua:
        device = "iPhone"
    elif "iPad" in ua:
        device = "iPad"
    elif "Android" in ua:
        device = "Android"
    elif "Windows" in ua:
        device = "Windows"
    elif "Macintosh" in ua or "Mac OS X" in ua:
        device = "Mac"
    elif "CrOS" in ua:
        device = "Chromebook"
    elif "Linux" in ua or "X11" in ua:
        device = "Linux"
    else:
        device = _t("Appareil inconnu")

    # Edge, Opera and the iOS browsers also say "Chrome" or "Safari": test them first.
    if "Edg/" in ua or "EdgA/" in ua or "EdgiOS/" in ua:
        browser = "Edge"
    elif "OPR/" in ua or "Opera" in ua:
        browser = "Opera"
    elif "Firefox/" in ua or "FxiOS/" in ua:
        browser = "Firefox"
    elif "Chrome/" in ua or "CriOS/" in ua:
        browser = "Chrome"
    elif "Safari/" in ua:
        browser = "Safari"
    else:
        browser = _t("Navigateur inconnu")
    return device, browser


def relative_time(moment: datetime, now: datetime) -> str:
    seconds = max(0, int((now - moment).total_seconds()))
    if seconds < 90:
        return _t("à l'instant")
    minutes = seconds // 60
    if minutes < 60:
        return _t("il y a %(n)s min") % {"n": minutes}
    hours = minutes // 60
    if hours < 24:
        return _t("il y a %(n)s h") % {"n": hours}
    days = hours // 24
    return ngettext("il y a %(n)s jour", "il y a %(n)s jours", days) % {"n": days}


def list_sessions(db: Session, user_id: int, current_id: int | None) -> list[dict]:
    """The sessions of ONE account, ready to display: the current one first, then the
    most recently active. Never carries the secret session id (only a row number, sent in
    a POST body, which the closing routes check against the signed-in account)."""
    now = datetime.utcnow()
    rows = db.scalars(
        select(UserSession)
        .where(
            UserSession.user_id == user_id,
            UserSession.revoked_at.is_(None),
            UserSession.created_at > now - SESSION_LIFETIME,
        )
        .order_by(UserSession.last_seen_at.desc(), UserSession.id.desc())
    ).all()
    result = []
    for row in rows:
        device, browser = describe_user_agent(row.user_agent)
        is_current = row.id == current_id
        result.append(
            {
                "id": row.id,
                "device": device,
                "browser": browser,
                "is_current": is_current,
                "last_seen": _t("active maintenant") if is_current else relative_time(row.last_seen_at, now),
                "opened_on": format_date(row.created_at.date()),
            }
        )
    result.sort(key=lambda item: not item["is_current"])  # stable: keeps the activity order
    return result


def _end(db: Session, row: UserSession, now: datetime) -> None:
    if row.legacy_hash is not None:
        # Tombstone: the old token it came from must not be converted a second time.
        row.token_hash = None
        row.revoked_at = now
    else:
        db.delete(row)


def close_session(db: Session, user_id: int, session_id: int) -> bool:
    """Closes one session of the account. False when it does not exist OR belongs to
    another account: the caller cannot tell the two apart."""
    row = db.scalar(
        select(UserSession).where(
            UserSession.id == session_id,
            UserSession.user_id == user_id,
            UserSession.revoked_at.is_(None),
        )
    )
    if row is None:
        return False
    _end(db, row, datetime.utcnow())
    db.commit()
    return True


def close_other_sessions(db: Session, user_id: int, keep_id: int | None) -> int:
    """Closes every session of the account except `keep_id` (None: all of them)."""
    query = select(UserSession).where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
    if keep_id is not None:
        query = query.where(UserSession.id != keep_id)
    rows = db.scalars(query).all()
    now = datetime.utcnow()
    for row in rows:
        _end(db, row, now)
    db.commit()
    return len(rows)


def purge_expired_sessions(db: Session) -> None:
    db.execute(delete(UserSession).where(UserSession.created_at < datetime.utcnow() - SESSION_LIFETIME))
    db.commit()
