"""pending_check_payment_method

Généralise pending_checks au-delà des chèques papier : check_number devient
optionnel, une nouvelle colonne payment_method sert d'ancre de rapprochement
alternative pour les paiements via un intermédiaire (Wero, PayPal...) dont le
libellé bancaire ne dit jamais à qui/pourquoi. Voir crud.match_pending_checks.

Revision ID: e17b3c9f2a04
Revises: d92e6c3a7f18
Create Date: 2026-08-13

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e17b3c9f2a04"
down_revision: Union[str, None] = "d92e6c3a7f18"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("pending_checks", "check_number", existing_type=sa.String(length=50), nullable=True)
    op.add_column("pending_checks", sa.Column("payment_method", sa.String(length=50), nullable=True))


def downgrade() -> None:
    # Les lignes créées sans check_number (ancrées uniquement sur
    # payment_method) n'ont pas d'équivalent en arrière : elles perdraient
    # leur seule ancre de rapprochement. On les supprime plutôt que de
    # laisser check_number NULL dans une colonne redevenue NOT NULL, ce qui
    # ferait échouer la migration descendante.
    op.execute("DELETE FROM pending_checks WHERE check_number IS NULL")
    op.drop_column("pending_checks", "payment_method")
    op.alter_column("pending_checks", "check_number", existing_type=sa.String(length=50), nullable=False)
