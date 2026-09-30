"""cap_entries table ("Le Cap")

Revision ID: 4d5e6f7a8b9c
Revises: 3c4d5e6f7a8b
Create Date: 2026-08-28

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4d5e6f7a8b9c"
down_revision: Union[str, None] = "3c4d5e6f7a8b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "cap_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        # Premier jour du mois couvert, comme budgets.month — une ligne par
        # mois, pas de contrainte unique en base (appliquée en code par
        # crud.save_cap_entry, façon crud.save_budgets).
        sa.Column("month", sa.Date(), nullable=False),
        sa.Column("planned_income", sa.Numeric(15, 2), nullable=False),
        sa.Column("planned_essentiel", sa.Numeric(15, 2), nullable=False),
        sa.Column("planned_choix", sa.Numeric(15, 2), nullable=False),
        sa.Column("planned_imprevu", sa.Numeric(15, 2), nullable=False),
        sa.Column("intention", sa.String(length=500), nullable=True),
        # Les 4 réponses de réflexion portent sur le mois qui vient de se
        # terminer, mais sont saisies et enregistrées en même temps que le
        # cap du NOUVEAU mois (étape 3 du wizard est le seul point de
        # sauvegarde) : elles vivent donc sur la ligne du nouveau mois plutôt
        # que sur celle du mois précédent.
        sa.Column("reflection_unexpected", sa.Text(), nullable=True),
        sa.Column("reflection_regret", sa.Text(), nullable=True),
        sa.Column("reflection_proud", sa.Text(), nullable=True),
        sa.Column("reflection_worked_well", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("cap_entries")
