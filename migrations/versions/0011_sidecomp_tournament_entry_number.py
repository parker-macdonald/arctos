"""Move side competition entry numbers from per-comp to per-tournament.

Introduces ``sidecomp_entry_numbers``, which assigns each player one entry
number per tournament. The number is shared across every side competition the
player enters in that tournament, so a competitor carries a single number.

Existing per-comp ``sidecomp_registrations.entry_number`` values are collapsed
into one row per ``(tournament, player)`` ordered by the player's earliest
registration in the tournament, then the column and its per-comp unique
constraint are dropped.

Revision ID: 0011_sidecomp_tournament_entry_number
Revises: 0010_normalize_match_names
Create Date: 2026-06-11
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0011_sidecomp_tournament_entry_number"
down_revision: Union[str, Sequence[str], None] = "0010_normalize_match_names"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"
    if is_sqlite:
        bind.exec_driver_sql("PRAGMA foreign_keys = OFF")
    try:
        op.create_table(
            "sidecomp_entry_numbers",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("tournament_url", sa.String(length=100), nullable=False),
            sa.Column("player", sa.String(length=50), nullable=False),
            sa.Column("entry_number", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["tournament_url"], ["tournaments.url"]),
            sa.ForeignKeyConstraint(["player"], ["players.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("tournament_url", "player", name="uq_sidecomp_entry_numbers_tournament_player"),
            sa.UniqueConstraint(
                "tournament_url", "entry_number", name="uq_sidecomp_entry_numbers_tournament_entry_number"
            ),
        )

        # Collapse existing per-comp registrations into one number per
        # (tournament, player), ordered by the player's earliest registration.
        bind.exec_driver_sql(
            """
            INSERT INTO sidecomp_entry_numbers (tournament_url, player, entry_number, created_at)
            SELECT tournament_url,
                   player,
                   ROW_NUMBER() OVER (PARTITION BY tournament_url ORDER BY first_id) AS entry_number,
                   CURRENT_TIMESTAMP
            FROM (
                SELECT sc.event AS tournament_url,
                       r.player AS player,
                       MIN(r.id) AS first_id
                FROM sidecomp_registrations AS r
                JOIN sidecomps AS sc ON sc.id = r.comp
                GROUP BY sc.event, r.player
            ) AS collapsed
            """
        )

        with op.batch_alter_table("sidecomp_registrations") as batch_op:
            batch_op.drop_constraint("uq_sidecomp_registrations_comp_entry_number", type_="unique")
            batch_op.drop_column("entry_number")
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
            batch_op.add_column(sa.Column("entry_number", sa.Integer(), nullable=True))

        # Restore the prior per-comp numbering: 1..N per comp ordered by id.
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

        with op.batch_alter_table("sidecomp_registrations") as batch_op:
            batch_op.alter_column("entry_number", existing_type=sa.Integer(), nullable=False)
            batch_op.create_unique_constraint(
                "uq_sidecomp_registrations_comp_entry_number",
                ["comp", "entry_number"],
            )

        op.drop_table("sidecomp_entry_numbers")
    finally:
        if is_sqlite:
            bind.exec_driver_sql("PRAGMA foreign_keys = ON")
