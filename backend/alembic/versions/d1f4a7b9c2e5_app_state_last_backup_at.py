"""date of the last full backup made from the app

Revision ID: d1f4a7b9c2e5
Revises: c4e8a2b9f173
Create Date: 2026-10-18

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d1f4a7b9c2e5"
down_revision: Union[str, None] = "c4e8a2b9f173"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # NULL = aucune sauvegarde faite depuis l'application.
    op.add_column("app_state", sa.Column("last_backup_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("app_state", "last_backup_at")
