"""day of the month the budget month starts on

Revision ID: a7d1e4c9b2f5
Revises: f6b9d3e8a2c4
Create Date: 2026-10-19

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7d1e4c9b2f5"
down_revision: Union[str, None] = "f6b9d3e8a2c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "cap_settings",
        sa.Column("budget_start_day", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_column("cap_settings", "budget_start_day")
