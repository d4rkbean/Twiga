"""drop receipt file storage

Revision ID: 8b9c0d1e2f3a
Revises: 7a8b9c0d1e2f
Create Date: 2026-09-05

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8b9c0d1e2f3a"
down_revision: Union[str, None] = "7a8b9c0d1e2f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Le fichier de ticket/facture n'est plus conservé après extraction —
    # seules les lignes qui en sont tirées (receipt_items) sont gardées,
    # jamais le fichier lui-même. Colonnes encore vides pour tout le monde
    # (fonctionnalité tout juste ajoutée) : pas de perte de données réelle.
    op.drop_column("transactions", "receipt_original_name")
    op.drop_column("transactions", "receipt_filename")


def downgrade() -> None:
    op.add_column(
        "transactions", sa.Column("receipt_filename", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "transactions", sa.Column("receipt_original_name", sa.String(length=255), nullable=True)
    )
