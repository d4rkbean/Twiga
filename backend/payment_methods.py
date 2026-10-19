"""Détection automatique du moyen de paiement à partir d'un libellé.

Les moyens de paiement eux-mêmes ne sont plus définis ici : ils vivent dans
la table payment_methods (backend.models.PaymentMethod, gérée depuis
Paramètres > Moyens de paiement), voir crud.get_payment_methods_dict. Cette
détection reste une simple heuristique texte, indépendante de la base — elle
renvoie le NOM d'un moyen de paiement par défaut (voir la migration
b7d4e1f9a2c6), pas un code séparé : si l'un de ces moyens de paiement par
défaut est renommé ou supprimé, la détection peut renvoyer une valeur qui ne
correspond plus à aucune ligne existante, sans plus de conséquence qu'un
moyen de paiement non renseigné (champ facultatif, jamais de contrainte de
clé étrangère dessus).
"""

import time

# Ordre volontairement identique à la spec : une règle plus haut dans la
# liste gagne en cas d'ambiguïté (ex : "VIREMENT SEPA" contient à la fois
# "VIREMENT" et "SEPA" — la règle Virement, listée avant Prélèvement,
# l'emporte, ce qui est le bon résultat pour ce libellé précis).
_DETECTION_RULES: list[tuple[list[str], str]] = [
    (["CARTE", "CB", "TPE", "PAIEMENT PAR CARTE"], "CB"),
    (["CHEQUE", "CHQ", "CHEQ"], "Chèque"),
    (["VIREMENT", "VIR"], "Virement"),
    (["PRELEVEMENT", "PRELVT", "PRLV", "SEPA"], "Prélèvement"),
    (["RETRAIT", "DAB", "GAB"], "Espèces"),
    (["AVOIR", "REMBOURSEMENT"], "Virement"),
]


def detection_examples() -> list[tuple[str, str]]:
    """The words Twiga reads in a label and the mode each one gives, in priority order:
    [("CARTE, CB, TPE", "CB"), ...]. Shown by the Modes de paiement screen of the other way."""
    seen: dict[str, list[str]] = {}
    for keywords, name in _DETECTION_RULES:
        seen.setdefault(name, []).extend(keywords)
    return [(", ".join(words), name) for name, words in seen.items()]


def detect_payment_from_label(label: str | None) -> str | None:
    if not label:
        return None
    upper_label = label.upper()
    for keywords, name in _DETECTION_RULES:
        if any(keyword in upper_label for keyword in keywords):
            return name
    return None


# Icône Tabler par nom de moyen de paiement (insensible à la casse). Les
# moyens de paiement ajoutés par l'utilisateur (Wero, PayPal...) n'ont pas de
# mapping : ils retombent sur "wallet". PaymentMethod.icon en base reste un
# emoji, encore utilisé par les écrans pas encore migrés.
_ICON_NAMES = {
    "cb": "credit-card",
    "prélèvement": "refresh",
    "chèque": "writing",
    "espèces": "cash",
    "virement": "arrows-left-right",
    "débit différé": "clock",
}
_DEFAULT_ICON_NAME = "wallet"


# Icons offered by the picker of Paramètres > Modes de paiement (Tabler names,
# stored in PaymentMethod.icon). Rows created before the picker hold an emoji
# there: they keep the icon of the name mapping above.
PICKER_ICONS = [
    "credit-card",
    "cash",
    "writing",
    "refresh",
    "arrows-left-right",
    "clock",
    "wallet",
    "building-bank",
    "receipt",
    "gift",
    "coins",
    "pig-money",
]

# name (lowercase) -> chosen icon, read once from the table and dropped
# whenever a mode is created, renamed or deleted (see refresh_chosen_icons).
_chosen_icons: dict[str, str] | None = None
_chosen_icons_at = 0.0
_CHOSEN_ICONS_TTL = 30.0  # seconds: also covers a restore or a change made elsewhere


def refresh_chosen_icons() -> None:
    global _chosen_icons
    _chosen_icons = None


def _load_chosen_icons() -> dict[str, str]:
    global _chosen_icons, _chosen_icons_at
    if _chosen_icons is None or time.monotonic() - _chosen_icons_at > _CHOSEN_ICONS_TTL:
        from sqlalchemy import select

        from backend.database import SessionLocal
        from backend.models import PaymentMethod

        with SessionLocal() as db:
            rows = db.execute(select(PaymentMethod.name, PaymentMethod.icon)).all()
        _chosen_icons = {name.strip().lower(): icon for name, icon in rows if icon in PICKER_ICONS}
        _chosen_icons_at = time.monotonic()
    return _chosen_icons


def get_payment_method_icon_name(name: str | None) -> str:
    key = (name or "").strip().lower()
    chosen = _load_chosen_icons().get(key)
    if chosen:
        return chosen
    return _ICON_NAMES.get(key, _DEFAULT_ICON_NAME)


# Affichage des moyens de paiement par défaut dans la langue de l'utilisateur.
# Le NOM français reste la clé stockée en base (Transaction.payment_method,
# Rule.payment_method) : seul l'affichage est traduit, et un moyen ajouté par
# l'utilisateur (Wero, PayPal...) s'affiche tel quel.
from backend.i18n import lazy_gettext  # noqa: E402

_DISPLAY_LABELS = {
    "CB": lazy_gettext("CB"),
    "Chèque": lazy_gettext("Chèque"),
    "Virement": lazy_gettext("Virement"),
    "Prélèvement": lazy_gettext("Prélèvement"),
    "Espèces": lazy_gettext("Espèces"),
    "Débit différé": lazy_gettext("Débit différé"),
}


def get_payment_method_label(name: str | None) -> str:
    if not name:
        return ""
    label = _DISPLAY_LABELS.get(name)
    return str(label) if label is not None else name
