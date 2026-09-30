"""payment_methods table

Revision ID: b7d4e1f9a2c6
Revises: a1c9f2e7b3d4
Create Date: 2026-08-05

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b7d4e1f9a2c6"
down_revision: Union[str, None] = "a1c9f2e7b3d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DEFAULTS = [
    ("CB", "💳"), ("Prélèvement", "🔄"), ("Chèque", "📝"),
    ("Espèces", "💶"), ("Virement", "↔️"), ("Débit différé", "⏭️"),
]


def upgrade() -> None:
    table = op.create_table(
        "payment_methods",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("icon", sa.String(length=10), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
    )
    op.bulk_insert(
        table,
        [
            {"name": name, "icon": icon, "is_default": True, "display_order": i}
            for i, (name, icon) in enumerate(_DEFAULTS)
        ],
    )


def downgrade() -> None:
    op.drop_table("payment_methods")
