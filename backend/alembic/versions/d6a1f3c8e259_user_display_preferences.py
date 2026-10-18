"""user display preferences: interface variant, theme, density

Revision ID: d6a1f3c8e259
Revises: c4e8a2b9f173
Create Date: 2026-10-18

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d6a1f3c8e259"
down_revision: Union[str, None] = "c4e8a2b9f173"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Existing accounts keep the current look: classic interface, the theme
    # follows the system, normal density.
    op.add_column(
        "users", sa.Column("ui_variant", sa.String(length=20), nullable=False, server_default="classic")
    )
    op.add_column(
        "users", sa.Column("theme", sa.String(length=10), nullable=False, server_default="system")
    )
    op.add_column(
        "users", sa.Column("density", sa.String(length=12), nullable=False, server_default="normal")
    )


def downgrade() -> None:
    op.drop_column("users", "density")
    op.drop_column("users", "theme")
    op.drop_column("users", "ui_variant")
