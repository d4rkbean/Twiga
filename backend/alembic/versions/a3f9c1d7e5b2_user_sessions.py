"""user sessions: one row per signed-in device

Revision ID: a3f9c1d7e5b2
Revises: e2a7c4d9b1f6
Create Date: 2026-10-19

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3f9c1d7e5b2"
down_revision: Union[str, None] = "e2a7c4d9b1f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Sessions used to be stateless signed tokens. Nothing is copied here: a token
    # issued before this migration (no session id inside) is converted into a row
    # the first time it is presented, so nobody is signed out by the update.
    op.create_table(
        "user_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=True),
        sa.Column("legacy_hash", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.String(255), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("token_hash", name="uq_user_sessions_token_hash"),
        sa.UniqueConstraint("legacy_hash", name="uq_user_sessions_legacy_hash"),
    )
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_user_sessions_user_id", table_name="user_sessions")
    op.drop_table("user_sessions")
