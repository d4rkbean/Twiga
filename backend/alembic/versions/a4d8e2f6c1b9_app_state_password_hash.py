"""app state password hash

Le mot de passe de connexion devient géré en base (bcrypt, colonne
app_state.password_hash) plutôt qu'uniquement via la variable
d'environnement AUTH_PASSWORD, pour survivre aux redémarrages une fois
changé depuis Paramètres > Sécurité. Voir backend/auth.py.

Revision ID: a4d8e2f6c1b9
Revises: e17b3c9f2a04
Create Date: 2026-08-17

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a4d8e2f6c1b9"
down_revision: Union[str, None] = "e17b3c9f2a04"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("app_state", sa.Column("password_hash", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("app_state", "password_hash")
