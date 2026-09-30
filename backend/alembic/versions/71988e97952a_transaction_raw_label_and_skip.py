"""transaction raw_label and skipped_at

Revision ID: 71988e97952a
Revises: 94ddcd9a0b2f
Create Date: 2026-08-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "71988e97952a"
down_revision: Union[str, None] = "94ddcd9a0b2f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("transactions", sa.Column("raw_label", sa.String(length=255), nullable=True))
    op.execute("UPDATE transactions SET raw_label = label WHERE raw_label IS NULL")
    op.alter_column("transactions", "raw_label", nullable=False)

    op.add_column("transactions", sa.Column("skipped_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("transactions", "skipped_at")
    op.drop_column("transactions", "raw_label")
