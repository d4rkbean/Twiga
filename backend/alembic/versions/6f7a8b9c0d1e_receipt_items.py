"""receipt items

Revision ID: 6f7a8b9c0d1e
Revises: 5e6f7a8b9c0d
Create Date: 2026-09-05

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6f7a8b9c0d1e"
down_revision: Union[str, None] = "5e6f7a8b9c0d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Photo de ticket ou facture PDF jointe à une transaction (voir
    # backend/receipts_storage.py) : le fichier lui-même vit sur disque
    # (volume Docker dédié "receipts", jamais dans frontend/static/ donc
    # jamais accessible sans passer par le middleware d'auth), seul son nom
    # stocké (UUID) est en base. receipt_original_name garde le nom
    # d'origine pour l'affichage/téléchargement.
    op.add_column(
        "transactions", sa.Column("receipt_filename", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "transactions", sa.Column("receipt_original_name", sa.String(length=255), nullable=True)
    )

    # Détail ligne par ligne d'un ticket/facture — note historique
    # consultable depuis la transaction, ne participe PAS aux totaux de
    # catégorie (Budgets/Rapports/Le Cap continuent de sommer la
    # transaction entière sous sa catégorie unique habituelle).
    op.create_table(
        "receipt_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "transaction_id",
            sa.Integer(),
            sa.ForeignKey("transactions.id"),
            nullable=False,
        ),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("amount", sa.Numeric(15, 2), nullable=False),
        sa.Column(
            "category_id", sa.Integer(), sa.ForeignKey("categories.id"), nullable=True
        ),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        "ix_receipt_items_transaction_id", "receipt_items", ["transaction_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_receipt_items_transaction_id", table_name="receipt_items")
    op.drop_table("receipt_items")
    op.drop_column("transactions", "receipt_original_name")
    op.drop_column("transactions", "receipt_filename")
