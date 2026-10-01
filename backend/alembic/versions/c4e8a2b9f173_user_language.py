"""user language and number format

Revision ID: c4e8a2b9f173
Revises: b7c3a9e15d42
Create Date: 2026-10-01

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4e8a2b9f173"
down_revision: Union[str, None] = "b7c3a9e15d42"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Les comptes existants restent en français, comme avant.
    op.add_column(
        "users", sa.Column("language", sa.String(length=5), nullable=False, server_default="fr")
    )
    op.add_column("users", sa.Column("number_format", sa.String(length=10), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "number_format")
    op.drop_column("users", "language")
