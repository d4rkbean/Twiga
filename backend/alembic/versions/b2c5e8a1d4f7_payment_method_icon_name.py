"""payment method icons become Tabler icon names (room for the longest)

Revision ID: b2c5e8a1d4f7
Revises: a7d1e4c9b2f5
Create Date: 2026-10-19

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2c5e8a1d4f7"
down_revision: Union[str, None] = "a7d1e4c9b2f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("payment_methods", "icon", type_=sa.String(length=30), existing_type=sa.String(length=10))


def downgrade() -> None:
    op.alter_column("payment_methods", "icon", type_=sa.String(length=10), existing_type=sa.String(length=30))
