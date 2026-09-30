"""add recurring_patterns table

Revision ID: 6bda7dbcadef
Revises: f527d71c9bf4
Create Date: 2026-08-03

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6bda7dbcadef"
down_revision: Union[str, None] = "f527d71c9bf4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "recurring_patterns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("label_pattern", sa.String(length=255), nullable=False, unique=True),
        sa.Column("amount", sa.Numeric(15, 2), nullable=False),
        sa.Column("frequency_days", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("category_id", sa.Integer(), sa.ForeignKey("categories.id"), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("recurring_patterns")
