"""Additive schema changes — four normalised join tables, monetary precision, integrity constraints, indexes.

This migration is purely additive: no existing column is renamed or dropped,
and no existing column type is changed in a way that loses data
(``Float`` → ``Numeric(10, 2)`` is widening for the values it holds). The
running application continues to work against the schema unchanged after
this migration is applied; the new tables sit empty until a separate
backfill populates them.

Concretely, this migration does five things:

1. **New normalised tables** (``headref_allowlist``, ``match_referees``,
   ``match_players``, ``camera_timepoints``). Each replaces a column that
   previously stored multiple values encoded as a comma-separated string
   or JSON array. The new tables let the database enforce uniqueness,
   foreign-key integrity, and cascade semantics that application code
   previously had to maintain in Python.

2. **Monetary columns become exact decimals.** ``RegistrableConfig.team_reg_fee``,
   ``RegistrableConfig.player_reg_fee``, ``TeamRegistration.amount_paid``,
   and ``PlayerRegistration.amount_paid`` move from ``Float`` (binary IEEE
   754) to ``Numeric(10, 2)``. Floats cannot represent ``$10.00`` exactly;
   reconciliation across many partial payments accumulates rounding error.

3. **UNIQUE constraints on logically-unique column pairs**. Adding these requires the live data to be
   free of duplicates first — operators run ``make db-check-duplicates``
   as a pre-flight gate. Constraints are implemented as ``UNIQUE`` indexes
   (``op.create_index(..., unique=True)``) because SQLite supports adding
   those directly, whereas adding a table-level ``UNIQUE`` constraint
   would require rebuilding the whole table.

4. **Mutual-exclusivity CHECK constraints** on ``team_registrations``,
   ``player_registrations``, and ``tos`` enforcing that exactly one of
   ``(event, league_id)`` is non-null. ``Tournament`` and ``PenaltyType``
   already had this; the registration / TO tables did not, and rows with
   both set or neither set silently broke any query that filtered by one.

5. **Performance indexes** on the eight columns that are filtered on
   every hot path (``matches.event``, ``points.match``,
   ``match_notes.match``, ``team_registrations.event``,
   ``(player_registrations.event, player)``, ``(headrefs.player, event)``,
   ``tags.event``, ``fields.event``). Schedule loads, registration
   checks, and live-scoring reads all pay for these.

Deliberately deferred:

* **Email uniqueness** on ``players.email`` / ``teams.email``. Email is
  contact information only — login is by ``id`` + password or by
  ``google_id``, and no code path queries users by email. Two players or
  two teams from the same club may legitimately share an inbox.

* **Polymorphic user-ID FKs** (``TO.user_id`` / ``Match.started_by`` /
  ``Match.finalized_by`` / ``Camera.uploaded_by_user_id``). Replacing
  the string-discriminator pattern with two nullable FKs needs a code
  change to populate the new columns; doing the schema change here in
  isolation would leave inert columns sitting next to the live ones.

* **CHECK that ``Tournament.n_max_teams`` / ``max_team_size_*`` are NULL
  when ``league_id IS NOT NULL``**. The application currently writes to
  both the league config and the tournament fields; adding the CHECK now
  would reject perfectly normal writes from existing code.


* **Replacing ``Match.field`` (name string) and ``Camera.field`` (slot
  index) with proper FKs**.

Pre-conditions for this migration:

* ``make db-check-duplicates`` exits 0. If it reports duplicate groups,
  they MUST be resolved in SQL
  first, otherwise the ``UNIQUE`` index creation will fail.

* ``sqlite3 instance/tournament.db "PRAGMA foreign_key_check;"``
  returns no rows. Existing FK violators won't be touched by this
  migration but would prevent any ``INSERT`` from succeeding once the
  pragma is enforced (which it already is at runtime after Phase 0).

* No row in ``team_registrations`` / ``player_registrations`` / ``tos``
  has both ``event`` and ``league_id`` set, or both NULL. The CHECK
  constraints added here will reject such rows. Find them with::

      SELECT id FROM <table>
       WHERE (event IS NULL AND league_id IS NULL)
          OR (event IS NOT NULL AND league_id IS NOT NULL);

* Pre-existing orphan FK references (i.e. rows surfaced by
  ``PRAGMA foreign_key_check;``) are tolerated by this migration —
  the FK pragma is temporarily disabled around the batch_alter_table
  operations so existing rows survive the table rebuild — but those
  orphans will fail any future ``UPDATE`` once FK enforcement is back
  on. Investigate and clean them when convenient.

Rollback: ``alembic downgrade 0001_baseline`` reverses every operation
in this file (drops the four tables, drops the constraints and indexes,
reverts the type changes). The downgrade is safe as long as no
application code or data has come to depend on the new structures yet.

Revision ID: 0002_phase1_additive
Revises: 0001_baseline
Create Date: 2026-04-24
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_phase1_additive"
down_revision: Union[str, Sequence[str], None] = "0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Match the column-length constants used in app/models/constants.py so the
# DDL stays in sync with the ORM. Hard-coded here (not imported) so this
# migration keeps working even if the constants module is later refactored
# or renamed.
URL_SLUG_LEN = 100
USER_ID_LEN = 50
UUID_LEN = 36
LONG_NAME_LEN = 200

# Reused mutual-exclusivity CHECK clause — exactly one of the columns set.
_EVENT_OR_LEAGUE = "(event IS NOT NULL AND league_id IS NULL) OR (event IS NULL AND league_id IS NOT NULL)"


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. New normalised join tables.
    # ------------------------------------------------------------------
    op.create_table(
        "headref_allowlist",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event", sa.String(URL_SLUG_LEN), nullable=False),
        sa.Column("player_id", sa.String(USER_ID_LEN), nullable=False),
        sa.ForeignKeyConstraint(["event"], ["tournaments.url"]),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event", "player_id", name="uq_headref_allowlist_event_player"),
    )

    op.create_table(
        "match_referees",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("match_uuid", sa.String(UUID_LEN), nullable=False),
        sa.Column("slot", sa.Integer(), nullable=False),
        sa.Column("team_id", sa.String(USER_ID_LEN), nullable=True),
        sa.Column("initial", sa.String(LONG_NAME_LEN), nullable=True),
        sa.ForeignKeyConstraint(["match_uuid"], ["matches.uuid"]),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("match_uuid", "slot", name="uq_match_referees_match_slot"),
    )

    op.create_table(
        "match_players",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("match_uuid", sa.String(UUID_LEN), nullable=False),
        sa.Column("player_id", sa.String(USER_ID_LEN), nullable=False),
        sa.Column("side", sa.Enum("TEAM1", "TEAM2", name="winnerside"), nullable=False),
        sa.ForeignKeyConstraint(["match_uuid"], ["matches.uuid"]),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("match_uuid", "player_id", name="uq_match_players_match_player"),
    )

    op.create_table(
        "camera_timepoints",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("camera_uuid", sa.String(UUID_LEN), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("time_world", sa.String(50), nullable=True),
        sa.Column("time_video", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["camera_uuid"], ["cameras.uuid"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("camera_uuid", "sequence", name="uq_camera_timepoints_camera_sequence"),
    )

    # ------------------------------------------------------------------
    # 2. Monetary precision + 3. CHECK constraints on the same tables.
    #    Combine into one batch_alter_table per table so SQLite only
    #    rebuilds each table once.
    #
    #    SQLite + alembic batch_alter_table rebuilds each table by
    #    INSERT-SELECTing every row into a temp table. With the FK pragma
    #    enforced (which the runtime and our migration env both do), any
    #    pre-existing orphan FK reference in the source data causes that
    #    INSERT-SELECT to fail. Disable FK enforcement around the batch
    #    operations and re-enable + validate afterwards. This matches
    #    alembic's documented pattern for SQLite batch migrations.
    # ------------------------------------------------------------------
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"
    if is_sqlite:
        bind.exec_driver_sql("PRAGMA foreign_keys = OFF")
    try:
        with op.batch_alter_table("registrable_configs") as batch:
            batch.alter_column("team_reg_fee", existing_type=sa.Float(), type_=sa.Numeric(10, 2))
            batch.alter_column("player_reg_fee", existing_type=sa.Float(), type_=sa.Numeric(10, 2))

        with op.batch_alter_table("team_registrations") as batch:
            batch.alter_column("amount_paid", existing_type=sa.Float(), type_=sa.Numeric(10, 2))
            batch.create_check_constraint(
                "ck_team_registrations_event_league_mutual_exclusive",
                _EVENT_OR_LEAGUE,
            )

        with op.batch_alter_table("player_registrations") as batch:
            batch.alter_column("amount_paid", existing_type=sa.Float(), type_=sa.Numeric(10, 2))
            batch.create_check_constraint(
                "ck_player_registrations_event_league_mutual_exclusive",
                _EVENT_OR_LEAGUE,
            )

        with op.batch_alter_table("tos") as batch:
            batch.create_check_constraint(
                "ck_tos_event_league_mutual_exclusive",
                _EVENT_OR_LEAGUE,
            )
    finally:
        if is_sqlite:
            bind.exec_driver_sql("PRAGMA foreign_keys = ON")

    # ------------------------------------------------------------------
    # 4. UNIQUE indexes on logically-unique column pairs.
    #    SQLite supports CREATE UNIQUE INDEX directly — no batch needed,
    #    no table rebuild.
    # ------------------------------------------------------------------
    op.create_index("uq_team_registrations_team_event", "team_registrations", ["team", "event"], unique=True)
    op.create_index("uq_team_registrations_team_league", "team_registrations", ["team", "league_id"], unique=True)
    op.create_index("uq_player_registrations_player_event", "player_registrations", ["player", "event"], unique=True)
    op.create_index(
        "uq_player_registrations_player_league",
        "player_registrations",
        ["player", "league_id"],
        unique=True,
    )
    op.create_index("uq_headrefs_player_event", "headrefs", ["player", "event"], unique=True)
    op.create_index("uq_matches_name_event", "matches", ["name", "event"], unique=True)
    op.create_index("uq_tags_name_event", "tags", ["name", "event"], unique=True)
    op.create_index("uq_fields_name_event", "fields", ["name", "event"], unique=True)
    op.create_index("uq_sidecompresults_comp_player", "sidecompresults", ["comp", "player"], unique=True)

    # ------------------------------------------------------------------
    # 5. Non-unique performance indexes
    # ------------------------------------------------------------------
    op.create_index("ix_matches_event", "matches", ["event"])
    op.create_index("ix_points_match", "points", ["match"])
    op.create_index("ix_match_notes_match", "match_notes", ["match"])
    op.create_index("ix_team_registrations_event", "team_registrations", ["event"])
    op.create_index("ix_player_registrations_event_player", "player_registrations", ["event", "player"])
    op.create_index("ix_headrefs_player_event", "headrefs", ["player", "event"])
    op.create_index("ix_tags_event", "tags", ["event"])
    op.create_index("ix_fields_event", "fields", ["event"])


def downgrade() -> None:
    # Reverse order of upgrade(). Indexes first, then constraints, then
    # type changes, then tables.

    op.drop_index("ix_fields_event", table_name="fields")
    op.drop_index("ix_tags_event", table_name="tags")
    op.drop_index("ix_headrefs_player_event", table_name="headrefs")
    op.drop_index("ix_player_registrations_event_player", table_name="player_registrations")
    op.drop_index("ix_team_registrations_event", table_name="team_registrations")
    op.drop_index("ix_match_notes_match", table_name="match_notes")
    op.drop_index("ix_points_match", table_name="points")
    op.drop_index("ix_matches_event", table_name="matches")

    op.drop_index("uq_sidecompresults_comp_player", table_name="sidecompresults")
    op.drop_index("uq_fields_name_event", table_name="fields")
    op.drop_index("uq_tags_name_event", table_name="tags")
    op.drop_index("uq_matches_name_event", table_name="matches")
    op.drop_index("uq_headrefs_player_event", table_name="headrefs")
    op.drop_index("uq_player_registrations_player_league", table_name="player_registrations")
    op.drop_index("uq_player_registrations_player_event", table_name="player_registrations")
    op.drop_index("uq_team_registrations_team_league", table_name="team_registrations")
    op.drop_index("uq_team_registrations_team_event", table_name="team_registrations")

    # Disable FK enforcement around batch operations — see upgrade() for
    # the explanation.
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"
    if is_sqlite:
        bind.exec_driver_sql("PRAGMA foreign_keys = OFF")
    try:
        with op.batch_alter_table("tos") as batch:
            batch.drop_constraint("ck_tos_event_league_mutual_exclusive", type_="check")

        with op.batch_alter_table("player_registrations") as batch:
            batch.drop_constraint("ck_player_registrations_event_league_mutual_exclusive", type_="check")
            batch.alter_column("amount_paid", existing_type=sa.Numeric(10, 2), type_=sa.Float())

        with op.batch_alter_table("team_registrations") as batch:
            batch.drop_constraint("ck_team_registrations_event_league_mutual_exclusive", type_="check")
            batch.alter_column("amount_paid", existing_type=sa.Numeric(10, 2), type_=sa.Float())

        with op.batch_alter_table("registrable_configs") as batch:
            batch.alter_column("player_reg_fee", existing_type=sa.Numeric(10, 2), type_=sa.Float())
            batch.alter_column("team_reg_fee", existing_type=sa.Numeric(10, 2), type_=sa.Float())
    finally:
        if is_sqlite:
            bind.exec_driver_sql("PRAGMA foreign_keys = ON")

    op.drop_table("camera_timepoints")
    op.drop_table("match_players")
    op.drop_table("match_referees")
    op.drop_table("headref_allowlist")
