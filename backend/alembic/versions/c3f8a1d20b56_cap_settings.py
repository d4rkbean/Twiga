"""add cap_settings: d'où viennent les ressources du mois

Le rituel du Cap pré-remplit « revenus prévus » depuis les recettes du mois
précédent. Ce défaut ne vaut que pour un foyer dont le salaire tombe en fin
de mois : d'autres reçoivent leur paie en cours de mois, alimentent un
compte commun par virements, ou se fixent une enveloppe quand le revenu est
irrégulier.

Cette table (une seule ligne, id=1) porte ce choix, pour qu'une organisation
particulière reste une configuration et n'entre pas dans le moteur — lequel
ne connaît que le montant engagé, saisi dans le rituel.

Revision ID: c3f8a1d20b56
Revises: b7e4c1a9d2f8
Create Date: 2026-09-21

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3f8a1d20b56"
down_revision: Union[str, None] = "b7e4c1a9d2f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "cap_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "income_source",
            sa.String(length=30),
            nullable=False,
            server_default="recettes_precedent",
        ),
        sa.Column("income_account_id", sa.Integer(), nullable=True),
        sa.Column("income_fixed_amount", sa.Numeric(precision=15, scale=2), nullable=True),
        sa.ForeignKeyConstraint(["income_account_id"], ["accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    # La ligne unique est créée ici plutôt qu'à la volée : le réglage doit
    # exister dès le premier démarrage, y compris pour une instance neuve.
    op.execute(
        "INSERT INTO cap_settings (id, income_source) VALUES (1, 'recettes_precedent')"
    )


def downgrade() -> None:
    op.drop_table("cap_settings")
