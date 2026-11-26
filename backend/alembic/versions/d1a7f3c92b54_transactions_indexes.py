"""index sur transactions (date, compte, catégorie, validation)

Revision ID: d1a7f3c92b54
Revises: a3f9c1d7e5b2
Create Date: 2026-11-11

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d1a7f3c92b54"
down_revision: Union[str, None] = "a3f9c1d7e5b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDEXES = {
    "ix_transactions_date": ["date"],
    "ix_transactions_account_date": ["account_id", "date"],
    "ix_transactions_category_date": ["category_id", "date"],
    "ix_transactions_validated": ["validated"],
}


def upgrade() -> None:
    for name, cols in _INDEXES.items():
        op.create_index(name, "transactions", cols, if_not_exists=True)


def downgrade() -> None:
    for name in _INDEXES:
        op.drop_index(name, table_name="transactions", if_exists=True)
