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


def get_payment_method_icon_name(name: str | None) -> str:
    return _ICON_NAMES.get((name or "").strip().lower(), _DEFAULT_ICON_NAME)
