"""import history ("Derniers imports")

Revision ID: f6b9d3e8a2c4
Revises: e5a8c2d7f1b3
Create Date: 2026-10-19

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f6b9d3e8a2c4"
down_revision: Union[str, None] = "e5a8c2d7f1b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "import_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("imported_on", sa.Date(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("account_name", sa.String(length=255), nullable=False),
        sa.Column("lines", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duplicates", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("imported", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("import_logs")
