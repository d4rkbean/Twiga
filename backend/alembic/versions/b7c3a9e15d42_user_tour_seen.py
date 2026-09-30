"""user tour_seen_at (visite guidée réservée aux nouveaux comptes)

Revision ID: b7c3a9e15d42
Revises: d5b2e7c41a93
Create Date: 2026-09-30

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7c3a9e15d42"
down_revision: Union[str, None] = "d5b2e7c41a93"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("tour_seen_at", sa.DateTime(), nullable=True))
    # Les comptes qui se sont déjà connectés connaissent l'application. Un
    # compte jamais connecté (dont l'admin semé par la migration des
    # utilisateurs sur une installation neuve) verra la visite.
    op.execute("UPDATE users SET tour_seen_at = NOW() WHERE last_login IS NOT NULL")


def downgrade() -> None:
    op.drop_column("users", "tour_seen_at")
