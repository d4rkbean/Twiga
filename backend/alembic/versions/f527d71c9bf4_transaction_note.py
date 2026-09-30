"""add optional note to transactions

Revision ID: f527d71c9bf4
Revises: f3b6c9a2d1e4
Create Date: 2026-08-03

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f527d71c9bf4"
down_revision: Union[str, None] = "f3b6c9a2d1e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("transactions", sa.Column("note", sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column("transactions", "note")
