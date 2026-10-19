"""add the optional savings goal to the Cap entries

Revision ID: b4e8a1c7d935
Revises: d6a1f3c8e259
Create Date: 2026-10-19

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b4e8a1c7d935"
down_revision: Union[str, None] = "d6a1f3c8e259"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("cap_entries", sa.Column("savings_goal", sa.Numeric(precision=15, scale=2), nullable=True))


def downgrade() -> None:
    op.drop_column("cap_entries", "savings_goal")
