"""Icône emoji d'une catégorie déduite de son nom, pour La Savane.

Volontairement basé sur le NOM (mots-clés, recherche insensible à la casse)
plutôt que sur le champ Category.icon en base : la plupart des catégories
importées via QIF n'ont jamais d'icône renseignée, et ce mapping donne un
résultat pertinent immédiatement, sans configuration manuelle préalable.
"""

# (mots-clés, emoji, nom d'icône Tabler) : l'emoji sert encore aux écrans pas
# encore migrés (La Savane...), le nom Tabler aux lignes de la liste des
# opérations (voir get_category_icon_name).
_KEYWORD_ICONS: list[tuple[list[str], str, str]] = [
    (["alimentation", "courses", "restaurant", "supermarché", "supermarche"], "🍽️", "tools-kitchen-2"),
    (["auto", "moto", "voiture", "carburant", "essence", "transport"], "🚗", "car"),
    (["loisirs", "culture", "sport", "cinéma", "cinema", "musique", "jeux"], "🎭", "masks-theater"),
    (["abonnement", "facture", "internet", "téléphone", "telephone", "câble", "cable"], "🧾", "receipt-2"),
    (["logement", "maison", "loyer", "chauffage", "électricité", "electricite", "eau"], "🏠", "home"),
    (["santé", "sante", "médical", "medical", "pharmacie", "docteur"], "💊", "pill"),
    (["animaux", "animal", "vétérinaire", "veterinaire"], "🐾", "paw"),
    (["voyage", "vacances"], "✈️", "plane"),
    (["banque", "frais bancaire", "virement", "prélèvement", "prelevement"], "🏦", "building-bank"),
    (["salaire", "revenu", "paie"], "💼", "briefcase"),
    (["épargne", "epargne", "projet"], "🎯", "target"),
    (["cadeau"], "🎁", "gift"),
    (["vêtement", "vetement", "shopping", "habillement"], "👕", "shirt"),
    (["impôt", "impot", "taxe"], "🧾", "receipt-tax"),
    (["assurance"], "🛡️", "shield"),
]

_DEFAULT_ICON = "🏷️"
_DEFAULT_ICON_NAME = "tag"


def get_category_icon(name: str | None) -> str:
    if not name:
        return _DEFAULT_ICON
    lowered = name.lower()
    for keywords, icon, _name in _KEYWORD_ICONS:
        if any(keyword in lowered for keyword in keywords):
            return icon
    return _DEFAULT_ICON


def get_category_icon_name(name: str | None) -> str:
    # Même déduction par mots-clés que get_category_icon, mais renvoie le nom
    # d'un SVG du jeu vendorisé (backend/icons.py) plutôt qu'un emoji.
    if not name:
        return _DEFAULT_ICON_NAME
    lowered = name.lower()
    for keywords, _icon, icon_name in _KEYWORD_ICONS:
        if any(keyword in lowered for keyword in keywords):
            return icon_name
    return _DEFAULT_ICON_NAME
