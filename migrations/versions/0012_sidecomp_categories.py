"""Add side competition categories.

Introduces ``sidecomp_categories`` (a TO-defined list of categories per side
competition) and a nullable ``category`` FK on ``sidecomp_registrations``. A
NULL category means the comp has no categories (or the row predates them).

Revision ID: 0012_sidecomp_categories
Revises: 0011_sidecomp_tournament_entry_number
Create Date: 2026-06-11
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0012_sidecomp_categories"
down_revision: Union[str, Sequence[str], None] = "0011_sidecomp_tournament_entry_number"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"
    if is_sqlite:
        bind.exec_driver_sql("PRAGMA foreign_keys = OFF")
    try:
        op.create_table(
            "sidecomp_categories",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("comp", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["comp"], ["sidecomps.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("comp", "name", name="uq_sidecomp_categories_comp_name"),
        )

        with op.batch_alter_table("sidecomp_registrations") as batch_op:
            batch_op.add_column(sa.Column("category", sa.Integer(), nullable=True))
            batch_op.create_foreign_key(
                "fk_sidecomp_registrations_category",
                "sidecomp_categories",
                ["category"],
                ["id"],
            )
    finally:
        if is_sqlite:
            bind.exec_driver_sql("PRAGMA foreign_keys = ON")


def downgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"
    if is_sqlite:
        bind.exec_driver_sql("PRAGMA foreign_keys = OFF")
    try:
        with op.batch_alter_table("sidecomp_registrations") as batch_op:
            batch_op.drop_constraint("fk_sidecomp_registrations_category", type_="foreignkey")
            batch_op.drop_column("category")

        op.drop_table("sidecomp_categories")
    finally:
        if is_sqlite:
            bind.exec_driver_sql("PRAGMA foreign_keys = ON")
