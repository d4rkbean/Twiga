"""category pillar

Revision ID: 1a2b3c4d5e6f
Revises: a7c3f9e2b4d1
Create Date: 2026-08-28

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1a2b3c4d5e6f"
down_revision: Union[str, None] = "a7c3f9e2b4d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # NULL = hérite du parent (sous-catégorie) ou non défini (catégorie
    # racine, auquel cas la résolution retombe sur "choix" par défaut — voir
    # crud.resolve_category_pillar). Pas de server_default à "choix" ici :
    # contrairement à un booléen où NULL n'aurait pas de sens, NULL est un
    # état à part entière pour ce champ (distinct de "choix" explicitement
    # assigné), donc les catégories existantes restent NULL tant que la
    # migration de seed suivante (ou l'utilisateur via Paramètres >
    # Catégories) ne leur assigne pas une valeur.
    op.add_column("categories", sa.Column("pillar", sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column("categories", "pillar")
