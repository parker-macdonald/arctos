"""Add sidecomp_registrations table and sidecomps.created_at column.

Introduces a dedicated registration table for side competitions so player
sign-ups are tracked independently from result rows, and stamps each
``sidecomps`` row with its creation time. Both changes are purely
additive: existing data is unaffected, and the running application
continues to work against the schema unchanged after this migration is
applied (the new table sits empty until backfilled or written by the new
sign-up flow; ``created_at`` backfills via the server default).

Revision ID: 0006_sidecomp_registrations
Revises: 0005_rename_is_day_event
Create Date: 2026-05-06
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0006_sidecomp_registrations"
down_revision: Union[str, Sequence[str], None] = "0005_rename_is_day_event"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Match the column-length constants used in app/models/constants.py so the
# DDL stays in sync with the ORM. Hard-coded here (not imported) to keep
# this migration stable if the constants module is later refactored.
USER_ID_LEN = 50


def upgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"
    if is_sqlite:
        bind.exec_driver_sql("PRAGMA foreign_keys = OFF")
    try:
        op.create_table(
            "sidecomp_registrations",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("comp", sa.Integer(), nullable=False),
            sa.Column("player", sa.String(USER_ID_LEN), nullable=False),
            sa.Column(
                "registered_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.current_timestamp(),
            ),
            sa.Column(
                "registered_by_to",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.ForeignKeyConstraint(["comp"], ["sidecomps.id"]),
            sa.ForeignKeyConstraint(["player"], ["players.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("comp", "player", name="uq_sidecomp_registrations_comp_player"),
        )

        with op.batch_alter_table("sidecomps") as batch:
            batch.add_column(
                sa.Column(
                    "created_at",
                    sa.DateTime(),
                    nullable=False,
                    server_default=sa.func.current_timestamp(),
                )
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
        with op.batch_alter_table("sidecomps") as batch:
            batch.drop_column("created_at")

        op.drop_table("sidecomp_registrations")
    finally:
        if is_sqlite:
            bind.exec_driver_sql("PRAGMA foreign_keys = ON")
