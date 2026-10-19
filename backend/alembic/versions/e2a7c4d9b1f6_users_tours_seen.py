"""users: remember which screen tours were offered

Revision ID: e2a7c4d9b1f6
Revises: c9d2e5f8a1b4
Create Date: 2026-10-19

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e2a7c4d9b1f6"
down_revision: Union[str, None] = "c9d2e5f8a1b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # {screen id: date the tour was offered}. NULL = nothing offered yet, so an
    # existing account is invited once on each screen it opens next.
    op.add_column("users", sa.Column("tours_seen", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "tours_seen")
