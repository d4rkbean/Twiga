"""Familles de produits pour le détail d'un ticket de supermarché.

Vocabulaire volontairement séparé de l'arbre Category (Paramètres >
Catégories) : ces familles n'ont de sens que pour décomposer UN ticket
d'hypermarché (Leclerc, Intermarché...) en rayons, pas pour catégoriser une
transaction dans le reste de l'app (Budgets, Règles, Rapports...) où
"Animalerie" ou "Hygiène et beauté" n'ont rien à faire mélangées aux
catégories de dépense habituelles. Voir aussi Category.excluded_from_budget
pour la logique équivalente côté catégories de revenu.
"""
from decimal import Decimal

from backend.i18n import lazy_gettext

RECEIPT_FAMILIES: list[tuple[str, str, str]] = [
    ("fruits_legumes", "🥦", lazy_gettext("Fruits et légumes")),
    ("epicerie_salee", "🍝", lazy_gettext("Épicerie salée")),
    ("epicerie_sucree", "🍬", lazy_gettext("Épicerie sucrée")),
    ("pains_patisseries", "🥐", lazy_gettext("Pains et pâtisseries")),
    ("viandes_poissons", "🥩", lazy_gettext("Viandes et poissons")),
    ("laitiers_oeufs", "🥚", lazy_gettext("Laitiers et œufs")),
    ("charcuterie_traiteur", "🍖", lazy_gettext("Charcuterie et traiteur")),
    ("surgeles", "🧊", lazy_gettext("Surgelés")),
    ("boissons", "🥤", lazy_gettext("Boissons")),
    ("hygiene_beaute", "🧴", lazy_gettext("Hygiène et beauté")),
    ("animalerie", "🐾", lazy_gettext("Animalerie")),
    ("entretien_nettoyage", "🧹", lazy_gettext("Entretien et nettoyage")),
    ("maison_loisirs", "🛋️", lazy_gettext("Maison et loisirs")),
]

RECEIPT_FAMILY_LABELS: dict[str, str] = {code: label for code, _icon, label in RECEIPT_FAMILIES}
RECEIPT_FAMILY_ICONS: dict[str, str] = {code: icon for code, icon, _label in RECEIPT_FAMILIES}


def group_items_by_family(items) -> list[dict]:
    # Regroupe les lignes d'un ticket par rayon, dans l'ordre de
    # RECEIPT_FAMILIES (celui du magasin, pas l'ordre d'extraction), avec un
    # sous-total par rayon — un ticket de 25 articles est illisible en liste
    # plate. Les lignes sans rayon (non reconnues) finissent dans un groupe
    # "Sans rayon" en dernier, jamais perdues.
    buckets: dict[str | None, list] = {}
    for item in items:
        buckets.setdefault(item.family, []).append(item)

    def _build(code: str | None, icon: str, label: str, group_items: list) -> dict:
        return {
            "code": code,
            "icon": icon,
            "label": label,
            "items": group_items,
            "subtotal": sum((i.amount for i in group_items), Decimal("0.00")),
        }

    groups: list[dict] = []
    for code, icon, label in RECEIPT_FAMILIES:
        group_items = buckets.pop(code, None)
        if group_items:
            groups.append(_build(code, icon, label, group_items))

    # Rayon inconnu (donnée plus ancienne qu'une version du vocabulaire) :
    # affiché tel quel plutôt que silencieusement fondu dans "Sans rayon".
    for code in sorted(c for c in buckets if c is not None):
        groups.append(_build(code, "🏷️", code, buckets.pop(code)))

    if buckets.get(None):
        groups.append(_build(None, "🏷️", "Sans rayon", buckets[None]))

    return groups


def receipt_family_display(code: str | None) -> str:
    if not code:
        return ""
    icon = RECEIPT_FAMILY_ICONS.get(code, "")
    label = RECEIPT_FAMILY_LABELS.get(code, code)
    return f"{icon} {label}".strip()


# Détection par mots-clés (même principe que category_icons._KEYWORD_ICONS) :
# une heuristique texte sur le libellé produit extrait du ticket, jamais une
# lecture fiable à 100 % (abréviations, codes-produits, fautes de frappe du
# clavier de caisse...) — l'utilisateur reste libre de corriger le rayon
# proposé. Ordre volontairement pensé pour éviter les collisions entre
# familles proches (ex. "jambon" seulement dans charcuterie, jamais dans
# viandes_poissons, pour ne pas avoir à trancher entre les deux à chaque
# retriangulation). "surgeles" est vérifié EN PREMIER : "poisson surgelé" ou
# "pizza surgelée" doit aller au rayon surgelés, pas à viandes_poissons ou
# charcuterie_traiteur qui matcheraient sinon en premier.
_FAMILY_KEYWORDS: list[tuple[str, list[str]]] = [
    (
        "surgeles",
        [
            "surgele", "surgelé", "surgelés", "surgelee", "surgelée",
            "congele", "congelé", "congelee", "congelée", "glace", "sorbet",
            "esquimau",
        ],
    ),
    (
        "fruits_legumes",
        [
            "pomme", "poire", "banane", "orange", "citron", "clementine", "clémentine",
            "salade", "tomate", "carotte", "patate", "pdt", "oignon", "courgette",
            # "fruit"/"fruits" seul délibérément absent : trop souvent un
            # simple descripteur de goût sur un produit sucré ou une boisson
            # ("bonbons goûts fruits", "dessert de fruits") plutôt qu'un vrai
            # fruit/légume — voir guess_receipt_family, testé sur une
            # facture Intermarché où ça routait des bonbons ici par erreur.
            "poireau", "legume", "légume", "avocat", "champignon", "ail",
            "echalote", "échalote", "endive", "brocoli", "epinard", "épinard",
            "concombre", "poivron", "raisin", "fraise", "abricot", "peche", "pêche",
            "kiwi", "melon", "mangue", "ananas", "pasteque", "pastèque",
            "nectarine", "cerise", "haricot",
        ],
    ),
    (
        "viandes_poissons",
        [
            # "veau" seul délibérément absent : sous-chaîne de "nouveau"
            # ("NOUVEAU SOLDE" en pied de ticket routait vers ce rayon).
            "boeuf", "bœuf", "porc", "poulet", "dinde", "agneau", "steak",
            "escalope de veau", "roti de veau", "blanquette",
            "poisson", "saumon", "thon", "cabillaud", "colin", "crevette", "moule",
            "boucherie", "merguez", "cote de", "côte de", "escalope",
        ],
    ),
    (
        "charcuterie_traiteur",
        [
            "jambon", "saucisson", "saucisse", "pate", "pâté", "rillette",
            "charcuterie", "traiteur", "quiche", "pizza fraiche", "pizza fraîche",
            "chorizo", "terrine", "lardon", "magret",
        ],
    ),
    (
        "laitiers_oeufs",
        [
            "lait", "yaourt", "yaourts", "fromage", "beurre", "creme fraiche",
            "crème fraîche", "oeuf", "œuf", "oeufs", "œufs", "laitage", "camembert",
            "emmental", "mozzarella", "gruyere", "gruyère",
        ],
    ),
    (
        "pains_patisseries",
        [
            "pain", "baguette", "croissant", "brioche", "patisserie",
            "pâtisserie", "viennoiserie", "tarte", "eclair", "éclair",
            "boulangerie", "biscotte", "chausson",
        ],
    ),
    (
        "epicerie_sucree",
        [
            "sucre", "chocolat", "bonbon", "biscuit", "gateau", "gâteau",
            "confiture", "miel", "cereales", "céréales", "dessert", "nutella",
            "pate a tartiner", "pâte à tartiner", "compote", "sable", "sablé",
        ],
    ),
    (
        "epicerie_salee",
        [
            "pates", "pâtes", "riz", "farine", "huile", "vinaigre", "conserve",
            "sauce", "soupe", "chips", "moutarde", "cornichon", "epices", "épices",
            "bouillon", "semoule",
        ],
    ),
    (
        "boissons",
        [
            # "the"/"thé" seul délibérément absent : trop court, matche aussi
            # bien "thé vert" comme parfum d'un savon que comme boisson.
            "eau minerale", "eau minérale", "jus", "soda", "coca", "vin", "biere",
            "bière", "cafe", "café", "boisson", "limonade", "sirop",
            "champagne", "cidre", "the noir", "thé noir", "the vert glace",
            "thé glacé",
        ],
    ),
    (
        "animalerie",
        [
            # "chat" seul délibérément absent : sous-chaîne de "achat"
            # ("bons d'achat", très fréquent en pied de facture), qui
            # routait à tort vers Animalerie.
            "croquette", "litiere", "litière", "chien", "animalerie",
            "pate pour chien", "pate pour chat", "pour chats", "litiere pour chat",
            "friandise chat", "friandises chat",
        ],
    ),
    (
        "hygiene_beaute",
        [
            "shampooing", "shampoing", "savon", "dentifrice", "deodorant", "déodorant",
            "gel douche", "rasoir", "coton", "hygiene", "hygiène", "couche bebe",
            "couches", "maquillage", "brosse a dent", "brosse à dents", "parfum",
        ],
    ),
    (
        "entretien_nettoyage",
        [
            "lessive", "nettoyant", "eponge", "éponge", "sopalin", "papier toilette",
            "essuie-tout", "javel", "liquide vaisselle", "entretien", "nettoyage",
            "sac poubelle", "adoucissant", "lingette", "mouchoir",
        ],
    ),
    (
        "maison_loisirs",
        [
            # "deco"/"déco" seul délibérément absent : matche "DECORE" sur un
            # libellé de caisse abrégé (constaté : "LABELL PH 3P DECORE",
            # du papier toilette, routé en Maison et loisirs).
            "livre", "jouet", "jeu", "decoration", "décoration",
            "bougie", "ampoule", "pile",
            "papeterie", "loisirs", "bricolage", "vaisselle jetable",
        ],
    ),
]


def guess_receipt_family(label: str | None) -> str | None:
    if not label:
        return None
    lowered = label.lower()
    for family, keywords in _FAMILY_KEYWORDS:
        if any(keyword in lowered for keyword in keywords):
            return family
    return None
