"""project movements remember the account the money came from

Revision ID: e5a8c2d7f1b3
Revises: d6a1f3c8e259
Create Date: 2026-10-19

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5a8c2d7f1b3"
down_revision: Union[str, None] = "d6a1f3c8e259"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("project_movements", sa.Column("account_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_project_movements_account_id",
        "project_movements",
        "accounts",
        ["account_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_project_movements_account_id", "project_movements", type_="foreignkey")
    op.drop_column("project_movements", "account_id")
