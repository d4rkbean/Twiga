"""fix categories imported as flat "Parent:Enfant" strings

Revision ID: 8a25bd1e09e3
Revises: df175aa05ba5
Create Date: 2026-08-02

"""
import logging
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

logger = logging.getLogger("alembic.fix_colon_categories")

# revision identifiers, used by Alembic.
revision: str = "8a25bd1e09e3"
down_revision: Union[str, None] = "df175aa05ba5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    categories = sa.table(
        "categories",
        sa.column("id", sa.Integer),
        sa.column("name", sa.String),
        sa.column("icon", sa.String),
        sa.column("parent_id", sa.Integer),
    )

    all_rows = bind.execute(
        sa.select(categories.c.id, categories.c.name, categories.c.parent_id)
    ).all()

    # Catégories propres déjà en place (jamais une ligne à plat "Parent:
    # Enfant" elle-même), indexées pour retrouver/créer le parent et la
    # sous-catégorie sans jamais dupliquer ni confondre deux lignes mal
    # formées entre elles.
    top_level_id_by_name: dict[str, int] = {
        name: cat_id for cat_id, name, parent_id in all_rows if parent_id is None and ":" not in name
    }
    child_id_by_key: dict[tuple[str, int], int] = {
        (name, parent_id): cat_id
        for cat_id, name, parent_id in all_rows
        if parent_id is not None and ":" not in name
    }

    # Une catégorie "mal formée" est un import à plat du style
    # "Parent:Enfant" au lieu d'une vraie relation parent_id -> jamais une
    # vraie sous-catégorie normalement créée depuis la page Catégories ou un
    # import QIF sain (qui utilise "/" à l'intérieur d'un nom, jamais ":").
    malformed = [(cat_id, name) for cat_id, name, _parent_id in all_rows if ":" in name]

    flat_ids_to_delete: list[int] = []

    # Étape 1 : pour chaque ligne mal formée, résoudre parent + sous-
    # catégorie CIBLES (jamais la ligne à plat elle-même, dont l'id sera
    # supprimé à l'étape 2) et reporter TOUTES les références vers elle —
    # transactions, budgets, règles, et toute catégorie qui l'utiliserait
    # elle-même comme parent_id (une ligne à plat, ayant parent_id NULL,
    # ressemble à une vraie catégorie de premier niveau : la page Catégories
    # a pu déjà servir à créer une vraie sous-catégorie dessous avant que ce
    # correctif n'existe). Oublier ce dernier point fait échouer la
    # suppression avec un ForeignKeyViolation ("Key (id)=... is still
    # referenced from table categories").
    for category_id, raw_name in malformed:
        parent_name, child_name = raw_name.split(":", 1)
        parent_name = parent_name.strip()
        child_name = child_name.strip()

        if not parent_name or not child_name:
            logger.warning(
                "Catégorie %r (id=%s) contient ':' mais ne peut pas être scindée "
                "proprement (partie vide) : laissée inchangée.",
                raw_name,
                category_id,
            )
            continue

        parent_id = top_level_id_by_name.get(parent_name)
        if parent_id is None:
            # RETURNING explicite plutôt que result.inserted_primary_key : un
            # sa.table()/sa.column() "nu" ne porte pas les métadonnées de clé
            # primaire d'un vrai modèle déclaratif (cf. migration
            # 87f90bfece95), donc SQLAlchemy peut ne pas savoir quelle colonne
            # renvoyer après l'INSERT.
            parent_id = bind.execute(
                categories.insert()
                .values(name=parent_name, icon=None, parent_id=None)
                .returning(categories.c.id)
            ).scalar_one_or_none()
            if parent_id is None:
                logger.warning(
                    "Impossible de créer la catégorie parent %r : %r reste inchangée.",
                    parent_name,
                    raw_name,
                )
                continue
            top_level_id_by_name[parent_name] = parent_id

        subcategory_id = child_id_by_key.get((child_name, parent_id))
        if subcategory_id is None:
            subcategory_id = bind.execute(
                categories.insert()
                .values(name=child_name, icon=None, parent_id=parent_id)
                .returning(categories.c.id)
            ).scalar_one_or_none()
            if subcategory_id is None:
                logger.warning(
                    "Impossible de créer la sous-catégorie %r sous %r : %r reste inchangée.",
                    child_name,
                    parent_name,
                    raw_name,
                )
                continue
            child_id_by_key[(child_name, parent_id)] = subcategory_id

        for table_name in ("transactions", "budgets", "rules"):
            table = sa.table(table_name, sa.column("category_id", sa.Integer))
            bind.execute(
                sa.update(table)
                .where(table.c.category_id == category_id)
                .values(category_id=subcategory_id)
            )
        # Toute catégorie qui référençait la ligne à plat comme parent_id
        # (possible tant qu'elle avait parent_id NULL et ressemblait donc à
        # une catégorie de premier niveau valide) est reportée sur la
        # sous-catégorie nouvellement résolue.
        bind.execute(
            sa.update(categories)
            .where(categories.c.parent_id == category_id)
            .values(parent_id=subcategory_id)
        )

        flat_ids_to_delete.append(category_id)

    # Étape 2 : suppression des lignes à plat, maintenant sûre puisque plus
    # aucune table ne les référence (transactions, budgets, règles,
    # categories.parent_id ont toutes été reportées à l'étape 1).
    if flat_ids_to_delete:
        bind.execute(sa.delete(categories).where(categories.c.id.in_(flat_ids_to_delete)))


def downgrade() -> None:
    # Pas de downgrade automatique : les lignes à plat d'origine ont été
    # supprimées et remplacées par de vraies relations parent/enfant,
    # potentiellement fusionnées entre elles ou avec des catégories déjà
    # propres — impossible à reconstituer sans perte. À traiter manuellement
    # si nécessaire.
    pass
