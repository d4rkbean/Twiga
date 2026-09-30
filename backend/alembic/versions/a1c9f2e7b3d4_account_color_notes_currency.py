"""account color, notes, currency

Revision ID: a1c9f2e7b3d4
Revises: 6bda7dbcadef
Create Date: 2026-08-04

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "a1c9f2e7b3d4"
down_revision: Union[str, None] = "6bda7dbcadef"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("accounts", sa.Column("color", sa.String(length=7), nullable=True))
    op.add_column("accounts", sa.Column("notes", sa.String(length=500), nullable=True))
    op.add_column(
        "accounts",
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="EUR"),
    )


def downgrade() -> None:
    op.drop_column("accounts", "currency")
    op.drop_column("accounts", "notes")
    op.drop_column("accounts", "color")
