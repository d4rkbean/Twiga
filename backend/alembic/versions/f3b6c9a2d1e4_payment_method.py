"""add optional payment_method to transactions and rules

Revision ID: f3b6c9a2d1e4
Revises: 8a25bd1e09e3
Create Date: 2026-08-02

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f3b6c9a2d1e4"
down_revision: Union[str, None] = "8a25bd1e09e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("transactions", sa.Column("payment_method", sa.String(length=20), nullable=True))
    op.add_column("rules", sa.Column("payment_method", sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column("rules", "payment_method")
    op.drop_column("transactions", "payment_method")
