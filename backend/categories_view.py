"""What the Catégories screen of the other way says about the tree of categories.

The pillars of Le Cap (Essentiel, Choix, Imprévus) are what ties a category to
the monthly plan, so the screen answers one question first: is every category
in a pillar, and which ones have a pillar of their own. These helpers read a
tree that is already loaded and need no session.
"""

from __future__ import annotations

from backend.pillars import PILLAR_ORDER


def resolve(category) -> str:
    """The pillar a category counts in: its own, else its parent's, else Choix."""
    from backend.crud import resolve_category_pillar

    return resolve_category_pillar(category)


def overrides(categories: list) -> list:
    """Sub-categories that have a pillar different from the one they would inherit."""
    found = []
    for parent in categories:
        inherited = resolve(parent)
        found += [child for child in parent.children if child.pillar and child.pillar != inherited]
    return found


def pillar_summary(categories: list) -> list[dict]:
    """For each pillar, in order: the root categories that count in it, and the
    sub-categories that moved there on their own ("Logement › Mobilier")."""
    summary = {code: {"code": code, "roots": [], "moved": []} for code in PILLAR_ORDER}
    for parent in categories:
        code = resolve(parent)
        if code in summary:
            summary[code]["roots"].append(parent.name)
        for child in parent.children:
            if child.pillar and child.pillar != code and child.pillar in summary:
                summary[child.pillar]["moved"].append(f"{parent.name} › {child.name}")
    return [summary[code] for code in PILLAR_ORDER]


def unset_roots(categories: list) -> list:
    """Root categories with no pillar chosen (they count in Choix by default)."""
    return [parent for parent in categories if not parent.pillar]
