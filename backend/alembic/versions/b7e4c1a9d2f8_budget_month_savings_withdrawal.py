"""add budget_months table for the monthly savings withdrawal

Revision ID: b7e4c1a9d2f8
Revises: 9c0d1e2f3a4b
Create Date: 2026-09-13

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7e4c1a9d2f8"
down_revision: Union[str, None] = "9c0d1e2f3a4b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "budget_months",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("month", sa.Date(), nullable=False),
        sa.Column("savings_withdrawal", sa.Numeric(15, 2), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_budget_months_month", "budget_months", ["month"])


def downgrade() -> None:
    op.drop_index("ix_budget_months_month", table_name="budget_months")
    op.drop_table("budget_months")
