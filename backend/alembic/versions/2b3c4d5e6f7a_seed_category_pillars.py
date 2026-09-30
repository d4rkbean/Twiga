"""seed category pillars for "Le Cap"

Revision ID: 2b3c4d5e6f7a
Revises: 1a2b3c4d5e6f
Create Date: 2026-08-28

"""
import logging
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

logger = logging.getLogger("alembic.seed_category_pillars")

# revision identifiers, used by Alembic.
revision: str = "2b3c4d5e6f7a"
down_revision: Union[str, None] = "1a2b3c4d5e6f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Mapping par défaut proposé par l'utilisateur pour "Le Cap". Vérifié contre
# les catégories RÉELLEMENT présentes en base (import HomeBank historique) :
# certains noms du mapping d'origine n'existent pas tels quels (ex.
# "Logement" en catégorie racine, "Livraison", "Dons" en autonome, ou
# "Réparations" comme enfant direct d'Auto/moto — il n'existe qu'un
# "Entretien/réparations" légataire et un "réparations" à 3 niveaux sous
# Entretien). Ces entrées sont volontairement OMISES ci-dessous plutôt que
# rattachées par approximation : mieux vaut laisser l'utilisateur les
# assigner à la main (Paramètres > Catégories) qu'un mauvais mapping
# automatique. "Cadeaux" est un exemple réel de l'override enfant : son
# parent "Divers" est en Imprévu, mais Cadeaux lui-même est mis en Choix
# directement, démontrant le mécanisme d'héritage/override.
TOP_LEVEL: dict[str, str] = {
    "Alimentation": "essentiel",
    "Transport": "essentiel",
    "Auto/moto": "essentiel",
    "Abonnement/factures": "essentiel",
    "Santé": "essentiel",
    "Enfants": "essentiel",
    "Loisirs/culture/sport": "choix",
    "Habillement": "choix",
    "Vacances": "choix",
    "Placements": "choix",
    "Soin de la personne": "choix",
    "Frais bancaires": "imprevu",
    "Divers": "imprevu",
}

# (nom de la sous-catégorie, nom du parent) -> pilier
SUBCATEGORIES: dict[tuple[str, str], str] = {
    ("Courses", "Alimentation"): "essentiel",
    ("Cantine", "Alimentation"): "essentiel",
    ("Carburant", "Auto/moto"): "essentiel",
    ("Entretien", "Auto/moto"): "essentiel",
    ("Électricité", "Abonnement/factures"): "essentiel",
    ("Gaz", "Abonnement/factures"): "essentiel",
    ("Eau", "Abonnement/factures"): "essentiel",
    ("Internet", "Abonnement/factures"): "essentiel",
    ("Portable", "Abonnement/factures"): "essentiel",
    ("Restaurant", "Alimentation"): "choix",
    ("Cadeaux", "Divers"): "choix",  # override : Divers (parent) = imprevu
    ("Vétérinaire", "Animaux domestiques"): "imprevu",
}


def upgrade() -> None:
    bind = op.get_bind()
    categories = sa.table(
        "categories",
        sa.column("id", sa.Integer),
        sa.column("name", sa.String),
        sa.column("parent_id", sa.Integer),
        sa.column("pillar", sa.String),
    )

    for name, pillar in TOP_LEVEL.items():
        result = bind.execute(
            categories.update()
            .where(categories.c.name == name, categories.c.parent_id.is_(None))
            .values(pillar=pillar)
        )
        if result.rowcount == 0:
            logger.warning("Catégorie racine %r introuvable, pilier %r non assigné.", name, pillar)

    for (child_name, parent_name), pillar in SUBCATEGORIES.items():
        parent_id = bind.execute(
            sa.select(categories.c.id).where(
                categories.c.name == parent_name, categories.c.parent_id.is_(None)
            )
        ).scalar_one_or_none()
        if parent_id is None:
            logger.warning(
                "Catégorie parent %r introuvable, sous-catégorie %r non assignée.",
                parent_name,
                child_name,
            )
            continue

        result = bind.execute(
            categories.update()
            .where(categories.c.name == child_name, categories.c.parent_id == parent_id)
            .values(pillar=pillar)
        )
        if result.rowcount == 0:
            logger.warning(
                "Sous-catégorie %r (parent %r) introuvable, pilier %r non assigné.",
                child_name,
                parent_name,
                pillar,
            )


def downgrade() -> None:
    # Pas de downgrade destructif : ces piliers peuvent déjà être utilisés
    # par des agrégats Le Cap/Rapports au moment d'un rollback. À réinitialiser
    # manuellement (bouton "Réinitialiser" ou colonne pillar) si nécessaire.
    pass
