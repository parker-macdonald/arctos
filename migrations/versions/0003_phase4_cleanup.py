"""Drop legacy blob columns superseded by the Phase 1 normalised tables, plus deprecated columns.

This migration is the **point of no return** for the schema cleanup project.
After Phase 0 (FK pragma + alembic baseline), Phase 1 (additive normalised
tables, indexes, monetary precision, integrity CHECKs), Phase 2 (backfill),
and Phase 3 (dual-write then read-switchover), the application no longer
reads or writes the columns dropped here. Every read goes through the
``app.services.dual_write`` helpers against the new join tables; every
write target is the new tables. The columns dropped below carry no live
data the application still consumes.

Columns dropped, with the reason for each:

* ``tournaments.head_refs_allowed_list`` — superseded by the
  ``headref_allowlist`` join table (Phase 1). Was a comma-separated
  text column of player IDs with no FK enforcement.

* ``matches.refs`` — superseded by ``match_referees`` (Phase 1). Was a
  comma-separated text column of resolved team IDs with no FK enforcement
  and no slot-position invariant outside application code.

* ``matches.refs_initial`` — superseded by the ``initial`` column on
  ``match_referees`` (Phase 1). Was the parallel comma-separated text
  column of ASS expressions, sharing the same problems as ``refs``.

* ``matches.team1_players`` — superseded by ``match_players`` (Phase 1)
  with ``side = 'TEAM1'``. Was a JSON-array text column.

* ``matches.team2_players`` — superseded by ``match_players`` (Phase 1)
  with ``side = 'TEAM2'``. Same JSON-array shape as ``team1_players``.

* ``matches.nstonesperset`` — deprecated since the introduction of
  ``stones_per_set``. Both columns were writeable through Phase 3a's
  dual-write window so existing rows kept the values aligned; reads now
  use ``stones_per_set`` exclusively (§3.6).

* ``cameras.time_world`` — superseded by ``camera_timepoints.time_world``
  (Phase 1). Was a JSON-array text column of ISO timestamps.

* ``cameras.time_video`` — superseded by ``camera_timepoints.time_video``
  (Phase 1). Was the parallel JSON-array text column of float offsets.

* ``registrable_configs.registration_open`` — deprecated by the split into
  ``team_registration_open`` and ``player_registration_open`` (§3.6).
  Routes ignored writes to it for the dual-write window; reads now
  consult only the per-role flags.

* ``tournaments.n_max_teams``,
  ``tournaments.max_team_size_roster``,
  ``tournaments.max_team_size_field`` — duplicates of the same three
  columns on ``RegistrableConfig`` (§3.5). Application reads have used
  the ``RegistrableConfig`` copies exclusively since Phase 3b; the
  tournament-level columns held stale values for league tournaments and
  were a recurring source of bugs.

Pre-conditions:

* Phase 3b has been live for at least one full tournament cycle with no
  fallbacks to the legacy columns and CI green.
* ``make db-backup`` has been run immediately before applying this
  migration. The drops are irreversible at the data level — the
  ``downgrade`` recreates the columns as nullable but cannot recover
  values that were not preserved elsewhere.
* SQLite version ≥ 3.35.0 (released 2021) for native ``DROP COLUMN``;
  alembic's ``batch_alter_table`` is used here so older SQLite versions
  fall back to the table-rebuild path automatically.

Rollback: ``alembic downgrade 0002_phase1_additive`` recreates each
dropped column as nullable with its original SQL type. Application code
that referenced these columns has been removed, so a downgrade alone
does not restore the prior behaviour — the corresponding source-tree
revert is also required.

Revision ID: 0003_phase4_cleanup
Revises: 0002_phase1_additive
Create Date: 2026-04-27
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003_phase4_cleanup"
down_revision: Union[str, Sequence[str], None] = "0002_phase1_additive"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite + alembic batch_alter_table rebuilds each table by
    # INSERT-SELECTing every row into a temp table. Disable FK
    # enforcement around the rebuilds so any pre-existing orphan FK
    # references (which we tolerate at this layer — see Phase 1
    # migration for the same pattern) survive the rewrite.
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"
    if is_sqlite:
        bind.exec_driver_sql("PRAGMA foreign_keys = OFF")
    try:
        with op.batch_alter_table("tournaments") as batch:
            batch.drop_column("head_refs_allowed_list")
            batch.drop_column("n_max_teams")
            batch.drop_column("max_team_size_roster")
            batch.drop_column("max_team_size_field")

        with op.batch_alter_table("matches") as batch:
            batch.drop_column("refs")
            batch.drop_column("refs_initial")
            batch.drop_column("team1_players")
            batch.drop_column("team2_players")
            batch.drop_column("nstonesperset")

        with op.batch_alter_table("cameras") as batch:
            batch.drop_column("time_world")
            batch.drop_column("time_video")

        with op.batch_alter_table("registrable_configs") as batch:
            batch.drop_column("registration_open")
    finally:
        if is_sqlite:
            bind.exec_driver_sql("PRAGMA foreign_keys = ON")


def downgrade() -> None:
    # Recreate the dropped columns as nullable with their original SQL
    # type. Values are NOT restored; downgrade only restores the column
    # shape so a paired source-tree revert can run.
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"
    if is_sqlite:
        bind.exec_driver_sql("PRAGMA foreign_keys = OFF")
    try:
        with op.batch_alter_table("registrable_configs") as batch:
            batch.add_column(
                sa.Column("registration_open", sa.Boolean(), nullable=False, server_default=sa.false())
            )

        with op.batch_alter_table("cameras") as batch:
            batch.add_column(sa.Column("time_world", sa.Text(), nullable=True))
            batch.add_column(sa.Column("time_video", sa.Text(), nullable=True))

        with op.batch_alter_table("matches") as batch:
            batch.add_column(sa.Column("refs", sa.Text(), nullable=True))
            batch.add_column(sa.Column("refs_initial", sa.Text(), nullable=True))
            batch.add_column(sa.Column("team1_players", sa.Text(), nullable=True))
            batch.add_column(sa.Column("team2_players", sa.Text(), nullable=True))
            batch.add_column(sa.Column("nstonesperset", sa.Integer(), nullable=True))

        with op.batch_alter_table("tournaments") as batch:
            batch.add_column(sa.Column("head_refs_allowed_list", sa.Text(), nullable=True))
            batch.add_column(sa.Column("n_max_teams", sa.Integer(), nullable=True))
            batch.add_column(sa.Column("max_team_size_roster", sa.Integer(), nullable=True))
            batch.add_column(sa.Column("max_team_size_field", sa.Integer(), nullable=True))
    finally:
        if is_sqlite:
            bind.exec_driver_sql("PRAGMA foreign_keys = ON")
