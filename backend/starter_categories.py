"""Catégories de départ proposées à une installation neuve.

Un jeu volontairement court et courant, pour ne pas partir d'une page
vide : l'utilisateur renomme, supprime ou complète ensuite (Paramètres >
Catégories). Jamais inséré automatiquement — uniquement sur action
explicite (voir crud.seed_starter_categories), pour ne pas s'ajouter à des
catégories déjà importées ou à une sauvegarde JSON restaurée ensuite.

Les noms contiennent des mots-clés de backend/category_icons.py quand c'est
possible (« Alimentation », « Santé », « Loisirs »...), pour qu'elles
reçoivent une icône pertinente sans configuration.

Piliers « Le Cap » (backend/pillars.py) : une sous-catégorie à None hérite
de son parent, une valeur explicite la remplace.
"""

from typing import NamedTuple


class StarterCategory(NamedTuple):
    name: str
    pillar: str | None
    excluded_from_budget: bool
    children: list[tuple[str, str | None]]


STARTER_CATEGORIES: list[StarterCategory] = [
    StarterCategory(
        "Revenus",
        None,
        True,  # pas une dépense : masquée de l'écran Budgets
        [
            ("Salaire", None),
            ("Primes et bonus", None),
            ("Allocations et aides", None),
            ("Remboursements", None),
            ("Autres revenus", None),
        ],
    ),
    StarterCategory(
        "Logement",
        "essentiel",
        False,
        [
            ("Loyer ou crédit immobilier", None),
            ("Charges de copropriété", None),
            ("Électricité", None),
            ("Gaz", None),
            ("Eau", None),
            ("Chauffage", None),
            ("Assurance habitation", None),
            ("Travaux et entretien", None),
            ("Mobilier et équipement", "choix"),
        ],
    ),
    StarterCategory(
        "Alimentation",
        "essentiel",
        False,
        [
            ("Courses", None),
            ("Cantine et repas au travail", None),
            ("Restaurants et cafés", "choix"),
            ("Livraison de repas", "choix"),
        ],
    ),
    StarterCategory(
        "Transport",
        "essentiel",
        False,
        [
            ("Carburant", None),
            ("Transports en commun", None),
            ("Parking et péages", None),
            ("Entretien et réparations", None),
            ("Assurance auto", None),
            ("Taxi et VTC", "choix"),
        ],
    ),
    StarterCategory(
        "Abonnements et factures",
        "essentiel",
        False,
        [
            ("Internet", None),
            ("Téléphone mobile", None),
            ("Streaming et TV", "choix"),
            ("Services en ligne", "choix"),
        ],
    ),
    StarterCategory(
        "Santé",
        "essentiel",
        False,
        [
            ("Médecin et spécialistes", None),
            ("Pharmacie", None),
            ("Mutuelle", None),
            ("Dentiste et optique", None),
        ],
    ),
    StarterCategory(
        "Enfants",
        "essentiel",
        False,
        [
            ("Garde et école", None),
            ("Fournitures scolaires", None),
            ("Activités et loisirs", "choix"),
            ("Vêtements et jouets", "choix"),
        ],
    ),
    StarterCategory(
        "Animaux",
        "essentiel",
        False,
        [
            ("Alimentation des animaux", None),
            ("Vétérinaire", "imprevu"),
            ("Accessoires et soins", "choix"),
        ],
    ),
    StarterCategory(
        "Impôts et taxes",
        "essentiel",
        False,
        [
            ("Impôt sur le revenu", None),
            ("Taxe foncière", None),
            ("Autres taxes", None),
        ],
    ),
    StarterCategory(
        "Banque",
        "essentiel",
        False,
        [
            ("Frais de tenue de compte et cartes", None),
            ("Agios et frais exceptionnels", "imprevu"),
        ],
    ),
    StarterCategory(
        "Loisirs et culture",
        "choix",
        False,
        [
            ("Sport", None),
            ("Cinéma et spectacles", None),
            ("Livres et presse", None),
            ("Jeux et hobbies", None),
            ("Sorties", None),
        ],
    ),
    StarterCategory(
        "Shopping",
        "choix",
        False,
        [
            ("Vêtements", None),
            ("High-tech", None),
            ("Cadeaux", None),
            ("Achats divers", None),
        ],
    ),
    StarterCategory(
        "Soin de la personne",
        "choix",
        False,
        [
            ("Coiffeur et beauté", None),
            ("Bien-être", None),
        ],
    ),
    StarterCategory(
        "Vacances et voyages",
        "choix",
        False,
        [
            ("Hébergement", None),
            ("Billets de transport", None),
            ("Activités sur place", None),
            ("Autres frais de voyage", None),
        ],
    ),
    StarterCategory(
        "Épargne et placements",
        "choix",
        False,
        [
            ("Épargne mensuelle", None),
            ("Placements", None),
        ],
    ),
    StarterCategory(
        "Imprévus et divers",
        "imprevu",
        False,
        [
            ("Réparations exceptionnelles", None),
            ("Amendes et frais administratifs", None),
            ("Dépenses exceptionnelles", None),
            ("Dons et associations", "choix"),
        ],
    ),
]
