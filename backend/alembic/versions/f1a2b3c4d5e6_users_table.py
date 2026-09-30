"""users table (multi-user auth)

Remplace l'authentification à mot de passe unique (app_state.password_hash,
elle-même une évolution de AUTH_PASSWORD) par un système multi-utilisateur
avec rôles (admin/editor/viewer). Migration en douceur, sans perte de
compte :

1. Crée la table users.
2. Sème un compte admin "admin", avec pour mot de passe (par ordre de
   priorité) : le hash déjà en base (app_state.password_hash, si un mot de
   passe avait déjà été changé depuis Paramètres), sinon AUTH_PASSWORD
   (variable d'environnement, ancien mécanisme), sinon "changeme" (valeur
   par défaut de docker-compose.yml).
3. Ajoute app_state.session_secret (nouveau secret de signature des cookies
   de session, partagé par tous les utilisateurs — plus dérivé d'un mot de
   passe individuel désormais, voir backend/auth.py) et supprime
   app_state.password_hash, devenue obsolète.

Revision ID: f1a2b3c4d5e6
Revises: a4d8e2f6c1b9
Create Date: 2026-08-18

"""
import os
from datetime import datetime
from typing import Sequence, Union

import bcrypt
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, None] = "a4d8e2f6c1b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DEFAULT_PASSWORD = "changeme"


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(length=50), nullable=False, unique=True),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False, server_default="viewer"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_login", sa.DateTime(), nullable=True),
    )

    connection = op.get_bind()
    app_state_table = sa.table("app_state", sa.column("id"), sa.column("password_hash"))
    existing_hash = connection.execute(
        sa.select(app_state_table.c.password_hash).where(app_state_table.c.id == 1)
    ).scalar_one_or_none()

    if existing_hash:
        # Mot de passe déjà changé depuis Paramètres (ancien mécanisme) :
        # celui-là prime, sinon l'utilisateur perdrait le mot de passe qu'il
        # a lui-même choisi.
        password_hash = existing_hash.encode("utf-8")
    else:
        env_password = os.environ.get("AUTH_PASSWORD") or _DEFAULT_PASSWORD
        password_hash = bcrypt.hashpw(env_password.encode("utf-8"), bcrypt.gensalt())

    users_table = sa.table(
        "users",
        sa.column("id"),
        sa.column("username"),
        sa.column("hashed_password"),
        sa.column("role"),
        sa.column("is_active"),
        sa.column("created_at"),
    )
    op.bulk_insert(
        users_table,
        [
            {
                "username": "admin",
                "hashed_password": password_hash.decode("utf-8"),
                "role": "admin",
                "is_active": True,
                "created_at": datetime.utcnow(),
            }
        ],
    )

    op.add_column("app_state", sa.Column("session_secret", sa.String(length=64), nullable=True))
    op.drop_column("app_state", "password_hash")


def downgrade() -> None:
    op.add_column("app_state", sa.Column("password_hash", sa.String(length=255), nullable=True))

    # Fait le chemin inverse : le hash de l'admin (s'il existe encore)
    # redevient le mot de passe unique global.
    connection = op.get_bind()
    users_table = sa.table("users", sa.column("username"), sa.column("hashed_password"))
    admin_hash = connection.execute(
        sa.select(users_table.c.hashed_password).where(users_table.c.username == "admin")
    ).scalar_one_or_none()
    if admin_hash:
        app_state_table = sa.table("app_state", sa.column("id"), sa.column("password_hash"))
        connection.execute(
            app_state_table.update().where(app_state_table.c.id == 1).values(password_hash=admin_hash)
        )

    op.drop_column("app_state", "session_secret")
    op.drop_table("users")
