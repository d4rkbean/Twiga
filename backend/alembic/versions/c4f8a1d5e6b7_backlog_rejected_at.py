"""backlog_rejected_at

Revision ID: c4f8a1d5e6b7
Revises: 76ffd9bcc33a
Create Date: 2026-08-11

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4f8a1d5e6b7"
down_revision: Union[str, None] = "76ffd9bcc33a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Volontairement PAS de report de skipped_at -> backlog_rejected_at ici.
# Avant ce correctif, "✗ Non merci" dans le Backlog ET "Passer" dans La
# Savane posaient tous les deux skipped_at (même champ, deux actions
# distinctes) : impossible de distinguer après coup, pour une ligne donnée,
# laquelle des deux origines est en cause. Comme "Passer" dans La Savane a
# été largement plus utilisé que "✗ Non merci", copier skipped_at
# reproduirait le bug même que cette migration corrige (un Backlog qui
# semble vide). Laisser backlog_rejected_at NULL pour tout l'historique fait
# réapparaître dans le Backlog les quelques opérations réellement rejetées
# par le passé (il suffit de les rejeter à nouveau si besoin) plutôt que de
# garder tout le Backlog masqué à tort.
def upgrade() -> None:
    op.add_column(
        "transactions", sa.Column("backlog_rejected_at", sa.DateTime(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("transactions", "backlog_rejected_at")
