"""Dual-write helpers that keep the new normalised tables in sync with their legacy blob columns.

The application currently authoritative reads come from the historical
blob columns (``Tournament.head_refs_allowed_list``, ``Match.refs``,
``Match.team1_players`` / ``team2_players``,
``Camera.time_world`` / ``Camera.time_video``). The corresponding new
join tables — populated initially by ``scripts/backfill_normalised_tables.py``
— must continue to track every subsequent write so that switching reads
over later is a no-op.

Each ``sync_*`` function below is invoked immediately after the legacy
blob has been assigned and before ``db.session.commit()``. It reads the
in-memory value of the blob column, computes the desired set of rows in
the new table, and reconciles by inserting / updating / deleting as
necessary. The functions are idempotent: re-running on already-in-sync
data is a no-op.

Each ``assert_*_parity`` function is the read-side check used by tests
and (eventually) a CI consistency job. They compare the two
representations and raise ``AssertionError`` on drift. **All of these
are temporary** — once application reads have switched to the new tables
and the legacy columns are dropped (Phase 4), this module can be
deleted in its entirety.

Orphan-FK behaviour (consistent with the backfill script):

* ``HeadRefAllowList.player_id`` referring to a deleted player is
  skipped with a logger warning.
* ``MatchReferee.team_id`` referring to a deleted team is stored as
  ``None`` while preserving the original ASS expression in ``initial``.
* ``MatchPlayer.player_id`` referring to a deleted player is skipped
  with a logger warning.
"""

from __future__ import annotations

import json
import logging
from typing import Iterable

from sqlalchemy import select

from app.domain.enums import WinnerSide
from app.models import (
    Camera,
    CameraTimepoint,
    HeadRefAllowList,
    Match,
    MatchPlayer,
    MatchReferee,
    Player,
    Team,
    Tournament,
    db,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared parsing helpers. Kept local to this module so the dual-write code
# is self-contained — modifying the parser here can never accidentally break
# the production read paths in service / route code.
# ---------------------------------------------------------------------------


def _parse_csv_ids(raw: str | None) -> list[str]:
    """Split a comma-separated string into a list of trimmed non-empty entries."""
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def _parse_csv_with_blanks(raw: str | None) -> list[str]:
    """Split a CSV preserving slot positions; empty slots become ``""``."""
    if not raw:
        return []
    return [item.strip() for item in raw.split(",")]


def _parse_json_list(raw: str | None) -> list:
    """Parse a JSON list, returning ``[]`` for None / empty / malformed input."""
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    return parsed if isinstance(parsed, list) else []


def _existing_ids(model, query_filter) -> set:
    """Tiny helper for ``SELECT id FROM model WHERE ...`` returning a set."""
    return {row[0] for row in db.session.execute(select(model.id).where(query_filter)).all()}


# ---------------------------------------------------------------------------
# Sync functions. Each is callable as ``sync_x(parent_obj)`` and reconciles
# the corresponding normalised table to match the parent's current blob.
# ---------------------------------------------------------------------------


def sync_head_ref_allowlist(tournament: Tournament) -> None:
    """Reconcile ``headref_allowlist`` to match ``tournament.head_refs_allowed_list``.

    Inserts rows for player IDs newly added to the comma-separated list,
    deletes rows for player IDs no longer present, and skips orphan
    references (player IDs that don't exist in ``players``) with a
    warning.
    """
    desired = set(_parse_csv_ids(tournament.head_refs_allowed_list))

    # Filter to only player IDs that actually exist — match the backfill's
    # orphan-skipping behaviour rather than letting the FK pragma reject
    # the insert at flush time.
    if desired:
        present = _existing_ids(Player, Player.id.in_(desired))
        for orphan in desired - present:
            logger.warning(
                "head_ref_allowlist sync: tournament=%s references unknown player_id=%r; skipped",
                tournament.url,
                orphan,
            )
        desired = desired & present

    existing_rows = HeadRefAllowList.query.filter_by(event=tournament.url).all()
    existing_ids = {r.player_id for r in existing_rows}

    for pid in desired - existing_ids:
        db.session.add(HeadRefAllowList(event=tournament.url, player_id=pid))
    for row in existing_rows:
        if row.player_id not in desired:
            db.session.delete(row)


def sync_match_referees(match: Match) -> None:
    """Reconcile ``match_referees`` to match ``Match.refs`` / ``Match.refs_initial``.

    The two source columns are parallel CSVs. Slot ordering is preserved
    via ``MatchReferee.slot``. ``team_id`` references a real team if the
    string is a known team ID; otherwise it is stored as ``None`` and
    the original expression is kept in ``initial`` so a later resolver
    can re-attempt resolution.
    """
    refs = _parse_csv_with_blanks(match.refs)
    initials = _parse_csv_with_blanks(match.refs_initial)
    n = max(len(refs), len(initials))
    refs = refs + [""] * (n - len(refs))
    initials = initials + [""] * (n - len(initials))

    # Pre-resolve which of the candidate team IDs actually exist, so a slot
    # whose `refs[i]` is bogus stores `None` rather than tripping the FK.
    candidate_team_ids = {team_id for team_id in refs if team_id}
    valid_team_ids = _existing_ids(Team, Team.id.in_(candidate_team_ids)) if candidate_team_ids else set()

    existing = {r.slot: r for r in MatchReferee.query.filter_by(match_uuid=match.uuid).all()}
    desired_slots: set[int] = set()

    for slot, (team_id, initial) in enumerate(zip(refs, initials)):
        if not team_id and not initial:
            continue
        desired_slots.add(slot)
        resolved = team_id if team_id in valid_team_ids else None
        normalised_initial = initial or None
        if slot in existing:
            row = existing[slot]
            row.team_id = resolved
            row.initial = normalised_initial
        else:
            db.session.add(
                MatchReferee(
                    match_uuid=match.uuid,
                    slot=slot,
                    team_id=resolved,
                    initial=normalised_initial,
                )
            )
    for slot, row in existing.items():
        if slot not in desired_slots:
            db.session.delete(row)


def sync_match_players(match: Match) -> None:
    """Reconcile ``match_players`` to match ``Match.team1_players`` / ``team2_players``.

    Each side's JSON array of player IDs becomes a set of ``MatchPlayer``
    rows tagged with the matching ``side``. The ``UNIQUE(match_uuid,
    player_id)`` constraint on the destination table means a player who
    appears on both sides simultaneously will only land on the side that
    is processed first; that combination is a data error and the second
    side is skipped with a warning.
    """
    desired: dict[str, WinnerSide] = {}
    for side, raw in ((WinnerSide.TEAM1, match.team1_players), (WinnerSide.TEAM2, match.team2_players)):
        for pid in _parse_json_list(raw):
            if not pid:
                continue
            if pid in desired and desired[pid] != side:
                logger.warning(
                    "match_players sync: match=%s player_id=%r appears on both sides; keeping side=%s",
                    match.uuid,
                    pid,
                    desired[pid].value,
                )
                continue
            desired[pid] = side

    if desired:
        present_players = _existing_ids(Player, Player.id.in_(desired.keys()))
        for orphan in set(desired) - present_players:
            logger.warning(
                "match_players sync: match=%s references unknown player_id=%r; skipped",
                match.uuid,
                orphan,
            )
            del desired[orphan]

    existing = {r.player_id: r for r in MatchPlayer.query.filter_by(match_uuid=match.uuid).all()}
    for pid, side in desired.items():
        if pid in existing:
            existing[pid].side = side
        else:
            db.session.add(MatchPlayer(match_uuid=match.uuid, player_id=pid, side=side))
    for pid, row in existing.items():
        if pid not in desired:
            db.session.delete(row)


def sync_camera_timepoints(camera: Camera) -> None:
    """Reconcile ``camera_timepoints`` to match ``Camera.time_world`` / ``Camera.time_video``.

    The two source columns are parallel JSON arrays. If the lengths
    disagree (data corruption) the camera's destination rows are cleared
    rather than silently producing misaligned interpolation anchors —
    matching the backfill's "skip the camera" policy.
    """
    worlds = _parse_json_list(camera.time_world)
    videos = _parse_json_list(camera.time_video)

    desired: dict[int, tuple[str | None, float | None]] = {}
    if len(worlds) == len(videos):
        for seq, (tw, tv) in enumerate(zip(worlds, videos)):
            desired[seq] = (tw, tv)
    elif worlds or videos:
        logger.warning(
            "camera_timepoints sync: camera=%s has mismatched array lengths "
            "(world=%d, video=%d); destination rows cleared",
            camera.uuid,
            len(worlds),
            len(videos),
        )

    existing = {r.sequence: r for r in CameraTimepoint.query.filter_by(camera_uuid=camera.uuid).all()}
    for seq, (tw, tv) in desired.items():
        if seq in existing:
            existing[seq].time_world = tw
            existing[seq].time_video = tv
        else:
            db.session.add(
                CameraTimepoint(
                    camera_uuid=camera.uuid,
                    sequence=seq,
                    time_world=tw,
                    time_video=tv,
                )
            )
    for seq, row in existing.items():
        if seq not in desired:
            db.session.delete(row)


# ---------------------------------------------------------------------------
# Parity assertions. Used by tests and a future CI consistency job to
# verify the two representations agree. Each raises AssertionError on
# drift. These are intentionally tolerant: the destination tables only
# need to contain the *resolvable* subset of the legacy data, since
# orphan refs are stored as `None` (refs) or skipped (players, head-refs).
# ---------------------------------------------------------------------------


def _ids_resolvable(model, ids: Iterable[str]) -> set[str]:
    """Return the subset of ``ids`` that exist as PK values on ``model``."""
    ids = {i for i in ids if i}
    if not ids:
        return set()
    return _existing_ids(model, model.id.in_(ids))


def assert_head_ref_allowlist_parity(tournament: Tournament) -> None:
    """``headref_allowlist`` rows for ``tournament`` match its CSV blob.

    Compares the *resolvable* subset (orphan player IDs in the legacy CSV
    are skipped during sync, so they're not expected to appear in the
    join table either).
    """
    legacy_ids = set(_parse_csv_ids(tournament.head_refs_allowed_list))
    legacy_resolvable = _ids_resolvable(Player, legacy_ids)
    new_ids = {r.player_id for r in HeadRefAllowList.query.filter_by(event=tournament.url).all()}
    assert legacy_resolvable == new_ids, (
        f"head_refs parity drift on {tournament.url}: legacy={legacy_resolvable} new={new_ids}"
    )


def assert_match_referees_parity(match: Match) -> None:
    """``match_referees`` rows for ``match`` match its ``refs``/``refs_initial`` blob.

    Verified at the slot level (slot index → (team_id, initial)). Orphan
    team IDs are expected to land with ``team_id=None`` in the new table.
    """
    refs = _parse_csv_with_blanks(match.refs)
    initials = _parse_csv_with_blanks(match.refs_initial)
    n = max(len(refs), len(initials))
    refs = refs + [""] * (n - len(refs))
    initials = initials + [""] * (n - len(initials))

    candidate_team_ids = {t for t in refs if t}
    valid_team_ids = _existing_ids(Team, Team.id.in_(candidate_team_ids)) if candidate_team_ids else set()

    expected: dict[int, tuple[str | None, str | None]] = {}
    for slot, (team_id, initial) in enumerate(zip(refs, initials)):
        if not team_id and not initial:
            continue
        expected[slot] = (
            team_id if team_id in valid_team_ids else None,
            initial or None,
        )

    actual = {r.slot: (r.team_id, r.initial) for r in MatchReferee.query.filter_by(match_uuid=match.uuid).all()}
    assert expected == actual, f"match_referees parity drift on {match.uuid}: legacy={expected} new={actual}"


def assert_match_players_parity(match: Match) -> None:
    """``match_players`` rows for ``match`` match its team1/team2 JSON arrays.

    Verified as a (player_id → side) mapping. Orphan player IDs are
    expected to be skipped (so they appear in the legacy blob but not
    in the new table); this assertion accounts for that.
    """
    legacy: dict[str, WinnerSide] = {}
    for side, raw in ((WinnerSide.TEAM1, match.team1_players), (WinnerSide.TEAM2, match.team2_players)):
        for pid in _parse_json_list(raw):
            if pid and pid not in legacy:
                legacy[pid] = side

    resolvable = _ids_resolvable(Player, legacy.keys())
    expected = {pid: side for pid, side in legacy.items() if pid in resolvable}

    actual = {r.player_id: r.side for r in MatchPlayer.query.filter_by(match_uuid=match.uuid).all()}
    assert expected == actual, f"match_players parity drift on {match.uuid}: legacy={expected} new={actual}"


def assert_camera_timepoints_parity(camera: Camera) -> None:
    """``camera_timepoints`` rows match the parallel JSON arrays.

    When the legacy arrays disagree in length (data corruption) the
    destination is expected to be empty per the ``sync_*`` policy;
    this assertion accounts for that.
    """
    worlds = _parse_json_list(camera.time_world)
    videos = _parse_json_list(camera.time_video)
    expected: dict[int, tuple[str | None, float | None]] = {}
    if len(worlds) == len(videos):
        for seq, (tw, tv) in enumerate(zip(worlds, videos)):
            expected[seq] = (tw, tv)

    actual = {
        r.sequence: (r.time_world, r.time_video) for r in CameraTimepoint.query.filter_by(camera_uuid=camera.uuid).all()
    }
    assert expected == actual, f"camera_timepoints parity drift on {camera.uuid}: legacy={expected} new={actual}"
