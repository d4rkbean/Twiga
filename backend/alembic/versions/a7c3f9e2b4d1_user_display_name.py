"""user display_name

Ajoute users.display_name (nullable, facultatif) : nom affiché dans le
nouveau menu utilisateur (sidebar desktop + bottom sheet mobile) à la place
du nom de connexion quand renseigné — voir routers/profile.py. Purement
cosmétique, jamais utilisé pour l'authentification (toujours username).

Revision ID: a7c3f9e2b4d1
Revises: f1a2b3c4d5e6
Create Date: 2026-08-19

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7c3f9e2b4d1"
down_revision: Union[str, None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("display_name", sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "display_name")
