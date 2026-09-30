"""app state

Revision ID: 7dc9a7f9986c
Revises: b8bbab43541c
Create Date: 2026-08-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "7dc9a7f9986c"
down_revision: Union[str, None] = "b8bbab43541c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "app_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("last_routine_month", sa.Date(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("app_state")
