"""The guided tour of each screen.

Every screen template declares its own steps in a `tour_steps` block, with the
`screen_tour` and `tour_step` template globals defined here:

    {% block tour_steps %}{{ screen_tour("savane", [
      tour_step('[data-tour="lot"]', _("Le lot"), _("Une carte à la fois."), "inbox"),
    ]) }}{% endblock %}

`_layout.html` reads the block, `_tour.html` / `other_way/_tour.html` hand it
to `tour.js`, which plays it when the user asks (Aide) or accepts the one-time
invitation on the first opening of the screen. What an account has already been
offered is remembered per screen in `users.tours_seen`.
"""

from __future__ import annotations

import json
from datetime import datetime

from jinja2 import pass_context
from markupsafe import Markup, escape

# Every screen that has a tour, with the page that hosts it. The key is what
# `users.tours_seen` stores and what the invitation route accepts; the path
# tells which role may write on the screen (a reader's tour drops its steps
# that explain a gesture the reader cannot make).
SCREEN_TOURS: dict[str, str] = {
    "savane": "/transactions/inbox",
    "backlog": "/backlog",
    "operations": "/transactions/list",
    "dashboard": "/dashboard",
    "month": "/cap/mid",
    "budgets": "/budgets",
    "cap": "/cap",
    "reports": "/reports",
    "projects": "/projects",
    "import": "/imports/new",
    "settings": "/settings",
    "accounts": "/accounts",
    "categories": "/categories",
    "rules": "/rules",
    "payment_methods": "/payment-methods",
    "recurring": "/recurring",
    "checks": "/checks",
    "users": "/users",
    "profile": "/profile",
}


def _paragraphs(text) -> str:
    """The step text as HTML paragraphs: one `<p>` per string, escaped like any template text."""
    parts = [text] if isinstance(text, str) else list(text)
    return "".join(f"<p>{escape(part)}</p>" for part in parts)


def tour_step(
    target: str,
    title,
    text,
    icon: str,
    *,
    position: str = "bottom",
    alt_target: str | None = None,
    alt_position: str | None = None,
    optional: bool = False,
    write: bool = False,
) -> dict:
    """One step of a screen tour.

    target       CSS selector of an element of THIS screen, `[data-tour="..."]` or `#id`
    alt_target   the same element at the other breakpoint, when `target` is hidden there
    text         one string or a list of strings (one paragraph each), kept short
    optional     the target can legitimately be missing (collapsed, empty list):
                 the tour skips it silently; the tests do not require it in the page
    write        the step explains a gesture that changes data: dropped for a role
                 that cannot write on the screen
    """
    step = {
        "icon": icon,
        "target": target,
        "position": position,
        "title": str(title),
        "text": _paragraphs(text),
    }
    if alt_target:
        step["altTarget"] = alt_target
        step["altPosition"] = alt_position or position
    if optional:
        step["optional"] = True
    if write:
        step["write"] = True
    return step


@pass_context
def screen_tour(context, screen: str, steps: list[dict]) -> Markup:
    """The JSON of a screen's tour, for the `tour_steps` block."""
    if screen not in SCREEN_TOURS:
        raise ValueError(f"Unknown tour screen: {screen!r}")
    from backend.templating import can_edit

    writable = can_edit(context, SCREEN_TOURS[screen])
    kept = [step for step in steps if writable or not step.get("write")]
    return Markup(json.dumps({"screen": screen, "steps": kept}, ensure_ascii=False).replace("<", "\\u003c"))


def from_json_filter(value):
    """The tour a `tour_steps` block rendered, or None when the screen has none."""
    text = str(value).strip()
    return json.loads(text) if text else None


def screens_seen(user) -> dict:
    """The screens already offered to an account, with the date."""
    return dict(getattr(user, "tours_seen", None) or {})


def mark_screen_seen(user, screen: str) -> bool:
    """Remember that `screen` was offered to `user`; False when it was already."""
    seen = screens_seen(user)
    if screen in seen:
        return False
    seen[screen] = datetime.utcnow().isoformat(timespec="seconds")
    user.tours_seen = seen  # a new dict: SQLAlchemy does not see an in-place change
    return True
