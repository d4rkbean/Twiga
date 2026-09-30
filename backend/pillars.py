"""Les 3 "piliers" de la fonctionnalité "Le Cap" : 🏠 Essentiel / 🌟 Choix /
🆘 Imprévu.

Codes stockés tels quels dans Category.pillar (String(20)) — pas de table
dédiée, même principe que account_types.py/payment_methods pour un petit
ensemble fixe de valeurs.
"""

PILLARS: dict[str, dict[str, str]] = {
    "essentiel": {"icon": "🏠", "label": "Essentiel"},
    "choix": {"icon": "🌟", "label": "Choix"},
    "imprevu": {"icon": "🆘", "label": "Imprévu"},
}

# Ordre d'affichage stable pour les dropdowns/légendes (dict Python déjà
# ordonné, mais explicite ici pour ne jamais dépendre de l'ordre de
# déclaration de PILLARS si quelqu'un le réorganise).
PILLAR_ORDER: list[str] = ["essentiel", "choix", "imprevu"]

_DEFAULT = {"icon": "🌟", "label": "Choix"}


def get_pillar(pillar_code: str | None) -> dict[str, str]:
    if not pillar_code:
        return _DEFAULT
    return PILLARS.get(pillar_code, _DEFAULT)


def get_pillar_icon(pillar_code: str | None) -> str:
    return get_pillar(pillar_code)["icon"]


def get_pillar_label(pillar_code: str | None) -> str:
    return get_pillar(pillar_code)["label"]
