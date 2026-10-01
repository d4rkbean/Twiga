"""Catégories de départ proposées à une installation neuve.

Un jeu volontairement court et courant, pour ne pas partir d'une page
vide : l'utilisateur renomme, supprime ou complète ensuite (Paramètres >
Catégories). Les noms sont traduits au moment de l'ajout (langue de l'utilisateur), puis stockés tels quels.
Jamais inséré automatiquement — uniquement sur action
explicite (voir crud.seed_starter_categories), pour ne pas s'ajouter à des
catégories déjà importées ou à une sauvegarde JSON restaurée ensuite.

Les noms contiennent des mots-clés de backend/category_icons.py quand c'est
possible (« Alimentation », « Santé », « Loisirs »...), pour qu'elles
reçoivent une icône pertinente sans configuration.

Piliers « Le Cap » (backend/pillars.py) : une sous-catégorie à None hérite
de son parent, une valeur explicite la remplace.
"""

from typing import NamedTuple

from backend.i18n import lazy_gettext


class StarterCategory(NamedTuple):
    name: object  # texte traduit à l'affichage (lazy_gettext)
    pillar: str | None
    excluded_from_budget: bool
    children: list[tuple[object, str | None]]


STARTER_CATEGORIES: list[StarterCategory] = [
    StarterCategory(
        lazy_gettext("Revenus"),
        None,
        True,  # pas une dépense : masquée de l'écran Budgets
        [
            (lazy_gettext("Salaire"), None),
            (lazy_gettext("Primes et bonus"), None),
            (lazy_gettext("Allocations et aides"), None),
            (lazy_gettext("Remboursements"), None),
            (lazy_gettext("Autres revenus"), None),
        ],
    ),
    StarterCategory(
        lazy_gettext("Logement"),
        "essentiel",
        False,
        [
            (lazy_gettext("Loyer ou crédit immobilier"), None),
            (lazy_gettext("Charges de copropriété"), None),
            (lazy_gettext("Électricité"), None),
            (lazy_gettext("Gaz"), None),
            (lazy_gettext("Eau"), None),
            (lazy_gettext("Chauffage"), None),
            (lazy_gettext("Assurance habitation"), None),
            (lazy_gettext("Travaux et entretien"), None),
            (lazy_gettext("Mobilier et équipement"), "choix"),
        ],
    ),
    StarterCategory(
        lazy_gettext("Alimentation"),
        "essentiel",
        False,
        [
            (lazy_gettext("Courses"), None),
            (lazy_gettext("Cantine et repas au travail"), None),
            (lazy_gettext("Restaurants et cafés"), "choix"),
            (lazy_gettext("Livraison de repas"), "choix"),
        ],
    ),
    StarterCategory(
        lazy_gettext("Transport"),
        "essentiel",
        False,
        [
            (lazy_gettext("Carburant"), None),
            (lazy_gettext("Transports en commun"), None),
            (lazy_gettext("Parking et péages"), None),
            (lazy_gettext("Entretien et réparations"), None),
            (lazy_gettext("Assurance auto"), None),
            (lazy_gettext("Taxi et VTC"), "choix"),
        ],
    ),
    StarterCategory(
        lazy_gettext("Abonnements et factures"),
        "essentiel",
        False,
        [
            (lazy_gettext("Internet"), None),
            (lazy_gettext("Téléphone mobile"), None),
            (lazy_gettext("Streaming et TV"), "choix"),
            (lazy_gettext("Services en ligne"), "choix"),
        ],
    ),
    StarterCategory(
        lazy_gettext("Santé"),
        "essentiel",
        False,
        [
            (lazy_gettext("Médecin et spécialistes"), None),
            (lazy_gettext("Pharmacie"), None),
            (lazy_gettext("Mutuelle"), None),
            (lazy_gettext("Dentiste et optique"), None),
        ],
    ),
    StarterCategory(
        lazy_gettext("Enfants"),
        "essentiel",
        False,
        [
            (lazy_gettext("Garde et école"), None),
            (lazy_gettext("Fournitures scolaires"), None),
            (lazy_gettext("Activités et loisirs"), "choix"),
            (lazy_gettext("Vêtements et jouets"), "choix"),
        ],
    ),
    StarterCategory(
        lazy_gettext("Animaux"),
        "essentiel",
        False,
        [
            (lazy_gettext("Alimentation des animaux"), None),
            (lazy_gettext("Vétérinaire"), "imprevu"),
            (lazy_gettext("Accessoires et soins"), "choix"),
        ],
    ),
    StarterCategory(
        lazy_gettext("Impôts et taxes"),
        "essentiel",
        False,
        [
            (lazy_gettext("Impôt sur le revenu"), None),
            (lazy_gettext("Taxe foncière"), None),
            (lazy_gettext("Autres taxes"), None),
        ],
    ),
    StarterCategory(
        lazy_gettext("Banque"),
        "essentiel",
        False,
        [
            (lazy_gettext("Frais de tenue de compte et cartes"), None),
            (lazy_gettext("Agios et frais exceptionnels"), "imprevu"),
        ],
    ),
    StarterCategory(
        lazy_gettext("Loisirs et culture"),
        "choix",
        False,
        [
            (lazy_gettext("Sport"), None),
            (lazy_gettext("Cinéma et spectacles"), None),
            (lazy_gettext("Livres et presse"), None),
            (lazy_gettext("Jeux et hobbies"), None),
            (lazy_gettext("Sorties"), None),
        ],
    ),
    StarterCategory(
        lazy_gettext("Shopping"),
        "choix",
        False,
        [
            (lazy_gettext("Vêtements"), None),
            (lazy_gettext("High-tech"), None),
            (lazy_gettext("Cadeaux"), None),
            (lazy_gettext("Achats divers"), None),
        ],
    ),
    StarterCategory(
        lazy_gettext("Soin de la personne"),
        "choix",
        False,
        [
            (lazy_gettext("Coiffeur et beauté"), None),
            (lazy_gettext("Bien-être"), None),
        ],
    ),
    StarterCategory(
        lazy_gettext("Vacances et voyages"),
        "choix",
        False,
        [
            (lazy_gettext("Hébergement"), None),
            (lazy_gettext("Billets de transport"), None),
            (lazy_gettext("Activités sur place"), None),
            (lazy_gettext("Autres frais de voyage"), None),
        ],
    ),
    StarterCategory(
        lazy_gettext("Épargne et placements"),
        "choix",
        False,
        [
            (lazy_gettext("Épargne mensuelle"), None),
            (lazy_gettext("Placements"), None),
        ],
    ),
    StarterCategory(
        lazy_gettext("Imprévus et divers"),
        "imprevu",
        False,
        [
            (lazy_gettext("Réparations exceptionnelles"), None),
            (lazy_gettext("Amendes et frais administratifs"), None),
            (lazy_gettext("Dépenses exceptionnelles"), None),
            (lazy_gettext("Dons et associations"), "choix"),
        ],
    ),
]
