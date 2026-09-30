"""add rule_suggestions: retrouver les règles proposées mais non validées

Les propositions de règles étaient éphémères : affichées après une
catégorisation, perdues si on ne cliquait pas. En catégorisation de masse
elles s'empilaient plus vite qu'on ne pouvait les traiter.

Les persister leur donne un endroit où être retrouvées (page Règles), et
permet de retenir un refus — sans quoi « Non merci » ne valait que pour
l'affichage courant.

Revision ID: d5b2e7c41a93
Revises: c3f8a1d20b56
Create Date: 2026-09-23

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d5b2e7c41a93"
down_revision: Union[str, None] = "c3f8a1d20b56"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "rule_suggestions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("keyword", sa.String(length=255), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("occurrences", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("dismissed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.ForeignKeyConstraint(["category_id"], ["categories.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    # Le couple (mot-clé, catégorie) est cherché à chaque catégorisation :
    # index dessus plutôt que sur keyword seul, c'est la requête réelle.
    op.create_index(
        "ix_rule_suggestions_keyword_category",
        "rule_suggestions",
        ["keyword", "category_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_rule_suggestions_keyword_category", table_name="rule_suggestions")
    op.drop_table("rule_suggestions")
