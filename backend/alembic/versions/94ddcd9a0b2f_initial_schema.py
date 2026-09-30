"""initial schema

Revision ID: 94ddcd9a0b2f
Revises:
Create Date: 2026-08-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "94ddcd9a0b2f"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "categories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("icon", sa.String(length=50), nullable=True),
        sa.Column(
            "parent_id", sa.Integer(), sa.ForeignKey("categories.id"), nullable=True
        ),
    )

    op.create_table(
        "accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column(
            "balance", sa.Numeric(15, 2), nullable=False, server_default="0"
        ),
    )

    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("target_amount", sa.Numeric(15, 2), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column(
            "current_amount", sa.Numeric(15, 2), nullable=False, server_default="0"
        ),
    )

    op.create_table(
        "transactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("amount", sa.Numeric(15, 2), nullable=False),
        sa.Column(
            "account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False
        ),
        sa.Column(
            "category_id", sa.Integer(), sa.ForeignKey("categories.id"), nullable=True
        ),
        sa.Column(
            "validated", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )

    op.create_table(
        "budgets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "category_id", sa.Integer(), sa.ForeignKey("categories.id"), nullable=False
        ),
        sa.Column("month", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(15, 2), nullable=False),
    )

    op.create_table(
        "rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("keyword", sa.String(length=255), nullable=False),
        sa.Column(
            "category_id", sa.Integer(), sa.ForeignKey("categories.id"), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_table("rules")
    op.drop_table("budgets")
    op.drop_table("transactions")
    op.drop_table("projects")
    op.drop_table("accounts")
    op.drop_table("categories")
