"""payment_method_db_driven

Les moyens de paiement des transactions/règles passent d'un dict Python
statique (codes courts : "cb", "cheque", "virement", "prelevement",
"especes", "differe") à la table payment_methods déjà créée par
b7d4e1f9a2c6, seule source désormais utilisée par l'application (voir
crud.get_payment_methods_dict) — jusqu'ici, un moyen de paiement ajouté
depuis Paramètres > Moyens de paiement n'était utilisable nulle part
ailleurs, les formulaires de l'appli continuant de lire l'ancien dict
statique. Cette migration :
  1. Élargit les deux colonnes VARCHAR(20) -> VARCHAR(50), pour matcher
     PaymentMethod.name (un nom personnalisé plus long lèverait sinon une
     erreur PostgreSQL dès la première tentative de l'utiliser).
  2. Renomme les valeurs déjà stockées (anciens codes courts) vers le nom
     exact de la ligne payment_methods correspondante, pour que l'historique
     continue de s'afficher/se filtrer correctement avec les nouveaux
     sélecteurs pilotés par la base.

Revision ID: d92e6c3a7f18
Revises: c4f8a1d5e6b7
Create Date: 2026-08-11

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d92e6c3a7f18"
down_revision: Union[str, None] = "c4f8a1d5e6b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (ancien code, nouveau nom) — nouveau nom = PaymentMethod.name tel que seedé
# par b7d4e1f9a2c6 pour les 6 moyens de paiement par défaut.
_RENAMES = [
    ("cb", "CB"),
    ("prelevement", "Prélèvement"),
    ("cheque", "Chèque"),
    ("especes", "Espèces"),
    ("virement", "Virement"),
    ("differe", "Débit différé"),
]


def upgrade() -> None:
    op.alter_column(
        "transactions", "payment_method", type_=sa.String(length=50), existing_nullable=True
    )
    op.alter_column("rules", "payment_method", type_=sa.String(length=50), existing_nullable=True)

    for old_code, new_name in _RENAMES:
        op.execute(
            sa.text("UPDATE transactions SET payment_method = :new WHERE payment_method = :old").bindparams(
                new=new_name, old=old_code
            )
        )
        op.execute(
            sa.text("UPDATE rules SET payment_method = :new WHERE payment_method = :old").bindparams(
                new=new_name, old=old_code
            )
        )


def downgrade() -> None:
    for old_code, new_name in _RENAMES:
        op.execute(
            sa.text("UPDATE transactions SET payment_method = :old WHERE payment_method = :new").bindparams(
                old=old_code, new=new_name
            )
        )
        op.execute(
            sa.text("UPDATE rules SET payment_method = :old WHERE payment_method = :new").bindparams(
                old=old_code, new=new_name
            )
        )

    op.alter_column(
        "transactions", "payment_method", type_=sa.String(length=20), existing_nullable=True
    )
    op.alter_column("rules", "payment_method", type_=sa.String(length=20), existing_nullable=True)
