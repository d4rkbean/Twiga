"""rule receipt family

Revision ID: 9c0d1e2f3a4b
Revises: 8b9c0d1e2f3a
Create Date: 2026-09-09

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9c0d1e2f3a4b"
down_revision: Union[str, None] = "8b9c0d1e2f3a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Commerces à famille de produit unique (boulangerie, primeur...) : une
    # règle peut proposer un rayon (voir backend/receipt_families.py) en plus
    # de sa catégorie habituelle — quand elle matche une transaction déjà
    # catégorisée "Courses" et sans aucune ligne de ticket, une ligne unique
    # couvrant tout le montant est ajoutée automatiquement (voir
    # crud._maybe_add_receipt_family_line), sans attendre une vraie facture.
    # Réservé en pratique aux règles ciblant "Courses" (seule catégorie où le
    # rapport par rayon a du sens) — imposé côté crud/formulaire, pas de
    # contrainte en base.
    op.add_column("rules", sa.Column("receipt_family", sa.String(length=30), nullable=True))


def downgrade() -> None:
    op.drop_column("rules", "receipt_family")
