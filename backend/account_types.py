"""Types de compte proposés dans le formulaire de gestion des comptes.

Codes stockés tels quels dans Account.type (String(50), déjà existant avant
cette fonctionnalité) — jamais de table dédiée, la liste est fixe et courte,
même principe que payment_methods.py.

Les comptes importés depuis un QIF portent le type brut du fichier (Bank,
Cash, CCard...), qui ne correspond à aucun de ces codes : get_account_type
renvoie alors un intitulé/icône par défaut plutôt que de planter, et
l'utilisateur peut réassigner un type propre via le formulaire d'édition.
"""

from backend.i18n import lazy_gettext

ACCOUNT_TYPES: dict[str, dict[str, str]] = {
    "courant": {"icon": "🏦", "label": lazy_gettext("Courant")},
    "epargne": {"icon": "💰", "label": lazy_gettext("Épargne")},
    "livret": {"icon": "📈", "label": lazy_gettext("Livret")},
    "cash": {"icon": "💵", "label": "Cash"},
    "autre": {"icon": "❓", "label": lazy_gettext("Autre")},
}

_DEFAULT = {"icon": "🏦", "label": lazy_gettext("Autre")}


def get_account_type(type_code: str | None) -> dict[str, str]:
    if not type_code:
        return _DEFAULT
    return ACCOUNT_TYPES.get(type_code.lower(), {"icon": _DEFAULT["icon"], "label": type_code})


def get_account_type_icon(type_code: str | None) -> str:
    return get_account_type(type_code)["icon"]


def get_account_type_label(type_code: str | None) -> str:
    return get_account_type(type_code)["label"]
