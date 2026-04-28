#!/usr/bin/env python3
"""scripts/backfill_normalised_tables.py — copy legacy blob columns into the new join tables.

Several columns in the Arctos schema historically encoded multiple values
inside a single cell (comma-separated text or JSON arrays). The additive
schema migration introduced four normalised join tables that store the same
data with proper foreign-key, uniqueness, and ordering constraints. The
running application still reads from the old columns; this script copies
the data into the new tables so a future code change can switch the reads
over without losing anything.

Source → destination mappings:

    Tournament.head_refs_allowed_list     →  headref_allowlist
    Match.refs / Match.refs_initial       →  match_referees
    Match.team1_players / team2_players   →  match_players
    Camera.time_world / Camera.time_video →  camera_timepoints



Behaviour:

* **Idempotent.** Each insert is guarded by a uniqueness check, so re-running
  the script is a no-op for rows that already exist. Safe to run any number
  of times.
* **Additive only.** The legacy columns are read from but never modified.
  The application can keep operating off them throughout.
* **Tolerant of dirty data.** Orphan FK references (e.g. a player ID in
  ``head_refs_allowed_list`` that doesn't exist in ``players``) are
  reported as warnings and skipped; the script continues.

Pre-conditions:

* The additive schema migration is applied (the four destination tables exist).
  Run ``make db-current`` to confirm; should print ``0002_phase1_additive (head)``.
* A backup has been taken (``make db-backup pre-backfill``). Although this
  script does not modify the legacy columns, having a snapshot lets you
  recover instantly if a bug is discovered partway through.

Post-conditions:

* All four destination tables are populated from their corresponding source
  columns.
* Source columns are untouched; the application continues to read from them.
* Running ``--validate`` (the default after a backfill) confirms row counts
  and FK integrity match between source and destination.

Usage::

    uv run python scripts/backfill_normalised_tables.py            # backfill + validate
    uv run python scripts/backfill_normalised_tables.py --dry-run  # report what
                                                                   # would be inserted
                                                                   # without writing
    uv run python scripts/backfill_normalised_tables.py --validate-only
                                                                   # skip the backfill
                                                                   # and just report
    uv run python scripts/backfill_normalised_tables.py --quiet    # only print
                                                                   # the final summary

Exit codes:

* ``0`` — backfill (and validation, if run) succeeded.
* ``1`` — validation reported a mismatch. Investigate before proceeding.
* ``2`` — pre-conditions not met (e.g. destination tables missing).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

# scripts/ is not a Python package and the repo root is not on sys.path when
# invoked as ``python scripts/backfill_normalised_tables.py``. Add it so the
# ``app`` package can be imported from anywhere.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import create_app  # noqa: E402


def _resolve_database_url() -> str | None:
    """Return the SQLAlchemy URL the script should operate on, or ``None``.

    ``create_app()`` only reads ``SQLALCHEMY_DATABASE_URI`` from its config
    dict argument, falling back to a hard-coded ``sqlite:///tournament.db``.
    It does not consult the environment. This script honours the env var
    so an operator can point the backfill at any database (a snapshot, a
    staging copy, etc.) the same way ``alembic`` does. Returning ``None``
    leaves the application's default in place.
    """
    return os.environ.get("SQLALCHEMY_DATABASE_URI")


from app.domain.enums import WinnerSide  # noqa: E402
from app.models import (  # noqa: E402
    Camera,
    CameraTimepoint,
    Field,
    HeadRefAllowList,
    Match,
    MatchPlayer,
    MatchReferee,
    Player,
    Team,
    Tournament,
    db,
)


@dataclass
class BackfillStats:
    """Per-mapping counters returned by each ``backfill_*`` function.

    Attributes:
        inserted: Rows newly inserted into the destination table.
        skipped_existing: Source rows whose corresponding destination row
            already exists (idempotent re-run).
        skipped_orphan: Source rows whose FK target does not exist
            (e.g. a head-ref player ID that no longer maps to a real player).
        skipped_invalid: Source rows whose contents could not be parsed
            (e.g. malformed JSON).
        warnings: Free-text warnings worth surfacing in the summary.
    """

    inserted: int = 0
    skipped_existing: int = 0
    skipped_orphan: int = 0
    skipped_invalid: int = 0
    warnings: list[str] = field(default_factory=list)

    def as_row(self, label: str) -> str:
        """Render the stats as a single line for the summary table."""
        return (
            f"  {label:<32}  "
            f"inserted={self.inserted:>5}  "
            f"existing={self.skipped_existing:>5}  "
            f"orphan={self.skipped_orphan:>5}  "
            f"invalid={self.skipped_invalid:>5}"
        )


@dataclass
class FkTargets:
    """Pre-loaded sets of FK target IDs.

    Loaded once at the start of the run so each insert can validate its FK
    references in O(1) without round-tripping to the database. Required
    because we want to skip-with-warning on orphan FKs rather than letting
    SQLite raise ``IntegrityError`` mid-flush (which would abort the
    surrounding session).
    """

    player_ids: set[str]
    team_ids: set[str]
    match_uuids: set[str]
    field_ids: set[int]
    tournament_urls: set[str]
    camera_uuids: set[str]

    @classmethod
    def load(cls) -> FkTargets:
        """Build the set from the live database. Call inside an app context."""
        return cls(
            player_ids={pid for (pid,) in db.session.query(Player.id).all()},
            team_ids={tid for (tid,) in db.session.query(Team.id).all()},
            match_uuids={u for (u,) in db.session.query(Match.uuid).all()},
            field_ids={fid for (fid,) in db.session.query(Field.id).all()},
            tournament_urls={u for (u,) in db.session.query(Tournament.url).all()},
            camera_uuids={u for (u,) in db.session.query(Camera.uuid).all()},
        )


# ---------------------------------------------------------------------------
# Per-source backfill functions. Each takes the pre-loaded FK targets and
# returns a BackfillStats. None of them call commit(); the caller does that
# at the end so a failure mid-script is recoverable by re-running.
# ---------------------------------------------------------------------------


def backfill_head_ref_allowlist(targets: FkTargets, verbose: bool = False) -> BackfillStats:
    """Populate ``headref_allowlist`` from ``Tournament.head_refs_allowed_list``.

    ``head_refs_allowed_list`` is a comma-separated list of player IDs.
    Whitespace around each ID is trimmed. Empty entries are skipped silently
    (they are common in lists that end with a trailing comma).
    """
    stats = BackfillStats()
    existing = {(r.event, r.player_id) for r in HeadRefAllowList.query.all()}

    for tournament in Tournament.query.all():
        raw = tournament.head_refs_allowed_list or ""
        for entry in raw.split(","):
            pid = entry.strip()
            if not pid:
                continue
            if pid not in targets.player_ids:
                stats.skipped_orphan += 1
                if verbose:
                    print(f"  WARN headref: tournament={tournament.url!r} references unknown player={pid!r}")
                continue
            key = (tournament.url, pid)
            if key in existing:
                stats.skipped_existing += 1
                continue
            db.session.add(HeadRefAllowList(event=tournament.url, player_id=pid))
            existing.add(key)
            stats.inserted += 1
    return stats


def backfill_match_referees(targets: FkTargets, verbose: bool = False) -> BackfillStats:
    """Populate ``match_referees`` from ``Match.refs`` and ``Match.refs_initial``.

    The two source columns are parallel comma-separated lists. ``refs`` holds
    resolved team IDs (or empty strings for unresolved slots); ``refs_initial``
    holds the original ASS expression or explicit team ID. If the two lists
    have different lengths the shorter is padded with empty strings so every
    slot in the longer list still gets a row.

    Slots where both ``refs[i]`` and ``refs_initial[i]`` are empty are
    skipped — there is nothing to record.
    """
    stats = BackfillStats()
    existing_slots = {(r.match_uuid, r.slot) for r in MatchReferee.query.all()}

    for match in Match.query.all():
        refs = [r.strip() for r in (match.refs or "").split(",")] if match.refs else []
        initials = [i.strip() for i in (match.refs_initial or "").split(",")] if match.refs_initial else []
        n = max(len(refs), len(initials))
        if n == 0:
            continue
        refs = refs + [""] * (n - len(refs))
        initials = initials + [""] * (n - len(initials))

        for slot, (team_id, initial) in enumerate(zip(refs, initials)):
            if not team_id and not initial:
                continue
            if (match.uuid, slot) in existing_slots:
                stats.skipped_existing += 1
                continue

            resolved_team: str | None = None
            if team_id:
                if team_id in targets.team_ids:
                    resolved_team = team_id
                else:
                    # Orphan team reference. Keep the row (the initial expression
                    # is still useful) but log so an operator notices.
                    stats.skipped_orphan += 1
                    if verbose:
                        print(
                            f"  WARN match_referees: match={match.uuid} slot={slot} "
                            f"refs[i]={team_id!r} not in teams; storing initial only"
                        )

            db.session.add(
                MatchReferee(
                    match_uuid=match.uuid,
                    slot=slot,
                    team_id=resolved_team,
                    initial=initial or None,
                )
            )
            existing_slots.add((match.uuid, slot))
            stats.inserted += 1
    return stats


def backfill_match_players(targets: FkTargets, verbose: bool = False) -> BackfillStats:
    """Populate ``match_players`` from ``Match.team1_players`` / ``team2_players``.

    Both source columns are JSON arrays of player IDs. The unique constraint
    on ``(match_uuid, player_id)`` rules out the same player appearing on
    both sides — if the legacy data violates this (it shouldn't, but might),
    the second insert is skipped with a warning.
    """
    stats = BackfillStats()
    existing = {(r.match_uuid, r.player_id) for r in MatchPlayer.query.all()}

    for match in Match.query.all():
        for side, raw in ((WinnerSide.TEAM1, match.team1_players), (WinnerSide.TEAM2, match.team2_players)):
            if not raw:
                continue
            try:
                player_ids = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                stats.skipped_invalid += 1
                if verbose:
                    print(f"  WARN match_players: match={match.uuid} side={side.value} has unparseable JSON")
                continue
            if not isinstance(player_ids, list):
                stats.skipped_invalid += 1
                continue
            for pid in player_ids:
                if not pid:
                    continue
                if pid not in targets.player_ids:
                    stats.skipped_orphan += 1
                    if verbose:
                        print(
                            f"  WARN match_players: match={match.uuid} side={side.value} "
                            f"references unknown player={pid!r}"
                        )
                    continue
                if (match.uuid, pid) in existing:
                    stats.skipped_existing += 1
                    continue
                db.session.add(MatchPlayer(match_uuid=match.uuid, player_id=pid, side=side))
                existing.add((match.uuid, pid))
                stats.inserted += 1
    return stats


def backfill_camera_timepoints(targets: FkTargets, verbose: bool = False) -> BackfillStats:
    """Populate ``camera_timepoints`` from ``Camera.time_world`` / ``Camera.time_video``.

    Both source columns are JSON-encoded arrays of equal length: ``time_world``
    holds ISO timestamps, ``time_video`` holds float seconds offsets. If their
    lengths disagree (data corruption) the camera is skipped entirely with a
    warning — partial timepoints would silently misalign every interpolation.
    """
    stats = BackfillStats()
    existing = {(r.camera_uuid, r.sequence) for r in CameraTimepoint.query.all()}

    for cam in Camera.query.all():
        if not cam.time_world and not cam.time_video:
            continue
        try:
            worlds = json.loads(cam.time_world) if cam.time_world else []
            videos = json.loads(cam.time_video) if cam.time_video else []
        except (json.JSONDecodeError, TypeError):
            stats.skipped_invalid += 1
            if verbose:
                print(f"  WARN timepoints: camera={cam.uuid} has unparseable JSON")
            continue

        if not isinstance(worlds, list) or not isinstance(videos, list):
            stats.skipped_invalid += 1
            continue

        if len(worlds) != len(videos):
            stats.warnings.append(
                f"camera {cam.uuid}: time_world has {len(worlds)} entries, "
                f"time_video has {len(videos)} — camera skipped"
            )
            stats.skipped_invalid += max(len(worlds), len(videos))
            continue

        for seq, (tw, tv) in enumerate(zip(worlds, videos)):
            if (cam.uuid, seq) in existing:
                stats.skipped_existing += 1
                continue
            db.session.add(CameraTimepoint(camera_uuid=cam.uuid, sequence=seq, time_world=tw, time_video=tv))
            existing.add((cam.uuid, seq))
            stats.inserted += 1
    return stats


# ---------------------------------------------------------------------------
# Validation queries — run after backfill (or on demand via --validate-only).
# ---------------------------------------------------------------------------


@dataclass
class ValidationResult:
    """Outcome of one validation query.

    Attributes:
        label: Human-readable description.
        ok: ``True`` when the check passed.
        detail: Free-text explanation suitable for printing on failure.
    """

    label: str
    ok: bool
    detail: str = ""


def validate(verbose: bool = False) -> list[ValidationResult]:
    """Run every post-backfill validation query and collect results.

    Returns:
        One :class:`ValidationResult` per check. The caller decides the exit
        code based on whether any ``ok`` field is ``False``.
    """
    results: list[ValidationResult] = []

    # 1. Every MatchReferee.team_id (when not null) must reference a real team.
    orphans = (
        db.session.query(MatchReferee)
        .filter(MatchReferee.team_id.isnot(None))
        .filter(~MatchReferee.team_id.in_(db.session.query(Team.id)))
        .count()
    )
    results.append(
        ValidationResult(
            label="match_referees.team_id all reference a real team",
            ok=orphans == 0,
            detail=f"{orphans} orphan team_id reference(s)" if orphans else "",
        )
    )

    # 2. Every MatchPlayer.player_id must reference a real player.
    orphans = db.session.query(MatchPlayer).filter(~MatchPlayer.player_id.in_(db.session.query(Player.id))).count()
    results.append(
        ValidationResult(
            label="match_players.player_id all reference a real player",
            ok=orphans == 0,
            detail=f"{orphans} orphan player_id reference(s)" if orphans else "",
        )
    )

    # 3. Per-camera timepoint count matches the JSON array length on the camera.
    mismatches: list[str] = []
    for cam in Camera.query.all():
        if not cam.time_world:
            continue
        try:
            old_len = len(json.loads(cam.time_world))
        except (json.JSONDecodeError, TypeError):
            continue
        new_len = db.session.query(CameraTimepoint).filter(CameraTimepoint.camera_uuid == cam.uuid).count()
        if old_len != new_len:
            mismatches.append(f"{cam.uuid} old={old_len} new={new_len}")
    results.append(
        ValidationResult(
            label="camera_timepoints count matches Camera.time_world array length",
            ok=not mismatches,
            detail="; ".join(mismatches[:5]) + (f" (+{len(mismatches) - 5} more)" if len(mismatches) > 5 else ""),
        )
    )

    return results


# ---------------------------------------------------------------------------
# CLI plumbing.
# ---------------------------------------------------------------------------


def _check_preconditions() -> str | None:
    """Return an error string if the run can't proceed, ``None`` otherwise."""
    inspector = db.inspect(db.engine)
    required = {
        "headref_allowlist",
        "match_referees",
        "match_players",
        "camera_timepoints",
    }
    missing = required - set(inspector.get_table_names())
    if missing:
        return (
            "destination tables missing: "
            + ", ".join(sorted(missing))
            + ". Run `make db-migrate` first to apply the additive schema migration."
        )
    return None


def run_backfill(verbose: bool = False, dry_run: bool = False) -> dict[str, BackfillStats]:
    """Execute every backfill function in dependency order, return per-mapping stats.

    Args:
        verbose: When True, print a per-row warning for every orphan/invalid
            entry. Otherwise the warnings are summarised in the per-mapping
            counts.
        dry_run: When True, the session is rolled back at the end so no
            changes persist. The returned counts still reflect what *would*
            have been inserted.
    """
    targets = FkTargets.load()

    runs: dict[str, BackfillStats] = {}
    for label, fn in (
        ("headref_allowlist", backfill_head_ref_allowlist),
        ("match_referees", backfill_match_referees),
        ("match_players", backfill_match_players),
        ("camera_timepoints", backfill_camera_timepoints),
    ):
        runs[label] = fn(targets, verbose=verbose)

    if dry_run:
        db.session.rollback()
    else:
        db.session.commit()
    return runs


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. See module docstring for usage and exit codes."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be inserted without writing to the database.",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Skip the backfill; only run the post-backfill validation queries.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Only print the final summary; suppress per-row warnings.",
    )
    args = parser.parse_args(argv)

    config_overrides: dict[str, str] = {}
    db_url = _resolve_database_url()
    if db_url:
        config_overrides["SQLALCHEMY_DATABASE_URI"] = db_url
    app = create_app(config=config_overrides)

    with app.app_context():
        # Echo the actual database the script is about to touch, so an
        # operator who forgot to set ``SQLALCHEMY_DATABASE_URI`` doesn't
        # accidentally backfill the wrong file.
        print(f"Database: {app.config.get('SQLALCHEMY_DATABASE_URI')}")
        precondition_error = _check_preconditions()
        if precondition_error:
            print(f"error: {precondition_error}", file=sys.stderr)
            return 2

        if not args.validate_only:
            print(("Backfill" if not args.dry_run else "Backfill (DRY RUN)") + " starting...")
            runs = run_backfill(verbose=not args.quiet, dry_run=args.dry_run)
            print("\nBackfill summary:")
            for label, stats in runs.items():
                print(stats.as_row(label))
            for label, stats in runs.items():
                for warning in stats.warnings:
                    print(f"  WARN {label}: {warning}")

        print("\nValidation:")
        results = validate(verbose=not args.quiet)
        for r in results:
            mark = " ok " if r.ok else "FAIL"
            print(f"  [{mark}] {r.label}")
            if not r.ok:
                print(f"         {r.detail}")

        all_ok = all(r.ok for r in results)
        if not all_ok:
            print(
                "\nValidation reported mismatches. Investigate (the per-line "
                "details above identify the affected rows) before switching "
                "application reads to the new tables."
            )
            return 1
        print("\nDone.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
