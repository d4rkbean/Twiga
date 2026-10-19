"""setting: show the household's accounts as tiles on the login page

Revision ID: c9d2e5f8a1b4
Revises: b2c5e8a1d4f7
Create Date: 2026-10-19

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c9d2e5f8a1b4"
down_revision: Union[str, None] = "b2c5e8a1d4f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Off by default: showing who lives here to anyone who reaches the login
    # page is a choice the administrator makes, not a default.
    op.add_column(
        "app_state",
        sa.Column("show_login_accounts", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("app_state", "show_login_accounts")
