"""category excluded from budget

Revision ID: 5e6f7a8b9c0d
Revises: 4d5e6f7a8b9c
Create Date: 2026-09-05

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5e6f7a8b9c0d"
down_revision: Union[str, None] = "4d5e6f7a8b9c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Une catégorie racine comme "Traitements et salaires" ou "Autres
    # revenus" (des rentrées d'argent, pas des dépenses) n'a aucun sens dans
    # l'écran Budgets — on ne "plafonne" pas un revenu. server_default
    # "false" : toutes les catégories existantes restent budgétisables par
    # défaut, l'utilisateur exclut explicitement les siennes depuis
    # Paramètres > Catégories (voir crud.get_budgetable_categories).
    op.add_column(
        "categories",
        sa.Column(
            "excluded_from_budget",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("categories", "excluded_from_budget")
