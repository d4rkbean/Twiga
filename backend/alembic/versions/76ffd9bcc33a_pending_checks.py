"""add pending_checks table

Revision ID: 76ffd9bcc33a
Revises: b7d4e1f9a2c6
Create Date: 2026-08-06

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "76ffd9bcc33a"
down_revision: Union[str, None] = "b7d4e1f9a2c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pending_checks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("check_number", sa.String(length=50), nullable=False),
        sa.Column("amount", sa.Numeric(15, 2), nullable=False),
        sa.Column("issued_date", sa.Date(), nullable=False),
        sa.Column("recipient", sa.String(length=255), nullable=True),
        sa.Column("category_id", sa.Integer(), sa.ForeignKey("categories.id"), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column(
            "matched_transaction_id",
            sa.Integer(),
            sa.ForeignKey("transactions.id"),
            nullable=True,
        ),
        sa.Column("matched_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("pending_checks")
