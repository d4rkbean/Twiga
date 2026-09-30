"""no-op (ancien semis de catégories d'une installation précise)

Revision ID: 87f90bfece95
Revises: 6e847afdc3ca
Create Date: 2026-08-02

"""
from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "87f90bfece95"
down_revision: Union[str, None] = "6e847afdc3ca"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Migration conservée (même identifiant) pour garder la chaîne Alembic
# intacte, mais sans effet : elle recréait à l'origine des catégories
# propres à une installation précise, ce qui n'a pas sa place dans une
# installation neuve. Les catégories viennent d'un import QIF ou de la
# restauration d'une sauvegarde.


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
