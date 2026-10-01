"""Les 3 "piliers" de la fonctionnalité "Le Cap" : 🏠 Essentiel / 🌟 Choix /
🆘 Imprévu.

Codes stockés tels quels dans Category.pillar (String(20)) — pas de table
dédiée, même principe que account_types.py/payment_methods pour un petit
ensemble fixe de valeurs.
"""

from backend.i18n import lazy_gettext

PILLARS: dict[str, dict[str, str]] = {
    "essentiel": {"icon": "🏠", "label": lazy_gettext("Essentiel")},
    "choix": {"icon": "🌟", "label": lazy_gettext("Choix")},
    "imprevu": {"icon": "🆘", "label": lazy_gettext("Imprévu")},
}

# Ordre d'affichage stable pour les dropdowns/légendes (dict Python déjà
# ordonné, mais explicite ici pour ne jamais dépendre de l'ordre de
# déclaration de PILLARS si quelqu'un le réorganise).
PILLAR_ORDER: list[str] = ["essentiel", "choix", "imprevu"]

_DEFAULT = {"icon": "🌟", "label": lazy_gettext("Choix")}


def get_pillar(pillar_code: str | None) -> dict[str, str]:
    if not pillar_code:
        return _DEFAULT
    return PILLARS.get(pillar_code, _DEFAULT)


def get_pillar_icon(pillar_code: str | None) -> str:
    return get_pillar(pillar_code)["icon"]


def get_pillar_label(pillar_code: str | None) -> str:
    return get_pillar(pillar_code)["label"]
