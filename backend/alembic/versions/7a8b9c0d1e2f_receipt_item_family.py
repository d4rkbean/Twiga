"""receipt item family

Revision ID: 7a8b9c0d1e2f
Revises: 6f7a8b9c0d1e
Create Date: 2026-09-05

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7a8b9c0d1e2f"
down_revision: Union[str, None] = "6f7a8b9c0d1e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Remplace category_id (FK vers l'arbre Category général — Alimentation,
    # Auto/moto...) par une famille de rayon fixe (voir
    # backend/receipt_families.py) : un ticket d'hypermarché se décompose en
    # rayons (fruits et légumes, hygiène et beauté, animalerie...) qui
    # n'ont pas leur place dans l'arbre Category utilisé partout ailleurs
    # (Budgets, Règles, Rapports). Table encore vide (fonctionnalité jamais
    # utilisée avant cette révision) : pas de migration de données à faire.
    op.drop_column("receipt_items", "category_id")
    op.add_column(
        "receipt_items", sa.Column("family", sa.String(length=30), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("receipt_items", "family")
    op.add_column(
        "receipt_items",
        sa.Column("category_id", sa.Integer(), sa.ForeignKey("categories.id"), nullable=True),
    )
