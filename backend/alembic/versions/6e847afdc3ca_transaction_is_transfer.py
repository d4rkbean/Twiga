"""transaction is_transfer

Revision ID: 6e847afdc3ca
Revises: 7dc9a7f9986c
Create Date: 2026-08-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "6e847afdc3ca"
down_revision: Union[str, None] = "7dc9a7f9986c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "transactions",
        sa.Column("is_transfer", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("transactions", "is_transfer")
