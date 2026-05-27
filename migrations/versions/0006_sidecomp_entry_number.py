"""Add entry_number column to sidecomp_registrations.

Adds a 1-indexed ``entry_number`` to each row in
``sidecomp_registrations``, unique within a comp. Existing rows are
backfilled per-comp ordered by ``id`` (earliest registration gets 1).

Revision ID: 0006_sidecomp_entry_number
Revises: 0005_sidecomp_open_close_description
Create Date: 2026-05-06
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0006_sidecomp_entry_number"
down_revision: Union[str, Sequence[str], None] = "0005_sidecomp_open_close_description"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"
    if is_sqlite:
        bind.exec_driver_sql("PRAGMA foreign_keys = OFF")
    try:
        # Add as nullable first.
        with op.batch_alter_table("sidecomp_registrations") as batch_op:
            batch_op.add_column(sa.Column("entry_number", sa.Integer(), nullable=True))

        # Backfill existing rows: per-comp, order by id, assign 1..N.
        # SQLite supports window functions in 3.25+ which is fine for the project.
        bind.exec_driver_sql(
            """
            UPDATE sidecomp_registrations
            SET entry_number = sub.rn
            FROM (
                SELECT id, ROW_NUMBER() OVER (PARTITION BY comp ORDER BY id) AS rn
                FROM sidecomp_registrations
            ) AS sub
            WHERE sidecomp_registrations.id = sub.id
            """
        )

        # Now make NOT NULL and add the unique constraint.
        with op.batch_alter_table("sidecomp_registrations") as batch_op:
            batch_op.alter_column("entry_number", existing_type=sa.Integer(), nullable=False)
            batch_op.create_unique_constraint(
                "uq_sidecomp_registrations_comp_entry_number",
                ["comp", "entry_number"],
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
            batch_op.drop_constraint("uq_sidecomp_registrations_comp_entry_number", type_="unique")
            batch_op.drop_column("entry_number")
    finally:
        if is_sqlite:
            bind.exec_driver_sql("PRAGMA foreign_keys = ON")
