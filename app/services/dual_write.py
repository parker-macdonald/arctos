"""Read/write helpers for the normalised join tables that supersede legacy blob columns.

These functions are the canonical interface for application code to access:

* ``HeadRefAllowList``  — replaces ``Tournament.head_refs_allowed_list``
* ``MatchReferee``      — replaces ``Match.refs`` and ``Match.refs_initial``
* ``MatchPlayer``       — replaces ``Match.team1_players`` / ``team2_players``
* ``CameraTimepoint``   — replaces ``Camera.time_world`` / ``time_video``

Each ``get_*`` reader queries the join table and returns data in the shape
callers expect (lists of IDs, ordered slot rows, parallel arrays). Each
``set_*`` / ``clear_*`` writer reconciles join-table rows against a desired
state expressed as parsed inputs. Callers no longer touch the legacy blob
columns; the columns remain in the schema but are no longer read or
written.

Orphan-FK behaviour:

* ``HeadRefAllowList.player_id`` referring to a non-existent player is
  skipped with a logger warning.
* ``MatchReferee.team_id`` referring to a non-existent team is stored as
  ``None`` while preserving the original ASS expression in ``initial``.
* ``MatchPlayer.player_id`` referring to a non-existent player is skipped
  with a logger warning.
"""

from __future__ import annotations

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
# Internal helpers
# ---------------------------------------------------------------------------


def _existing_ids(model, query_filter) -> set:
    """``SELECT id FROM model WHERE ...`` returned as a set."""
    return {row[0] for row in db.session.execute(select(model.id).where(query_filter)).all()}


def _split_csv_with_blanks(raw: str | None) -> list[str]:
    """Split a CSV preserving slot positions; empty slots become ``""``."""
    if not raw:
        return []
    return [item.strip() for item in raw.split(",")]


# ---------------------------------------------------------------------------
# HeadRefAllowList
# ---------------------------------------------------------------------------


def get_head_ref_allowlist_ids(tournament: Tournament) -> list[str]:
    """Return the player IDs on this tournament's head-referee allow-list."""
    rows = HeadRefAllowList.query.filter_by(event=tournament.url).order_by(HeadRefAllowList.id).all()
    return [r.player_id for r in rows]


def set_head_ref_allowlist_ids(tournament: Tournament, player_ids: Iterable[str]) -> None:
    """Reconcile the allow-list to contain exactly the given player IDs.

    Player IDs that don't exist in ``players`` are skipped with a warning,
    matching the orphan-FK policy used throughout the migration.
    """
    desired = {pid.strip() for pid in player_ids if pid and pid.strip()}

    if desired:
        present = _existing_ids(Player, Player.id.in_(desired))
        for orphan in desired - present:
            logger.warning(
                "head_ref_allowlist: tournament=%s references unknown player_id=%r; skipped",
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


def set_head_ref_allowlist_from_csv(tournament: Tournament, csv: str | None) -> None:
    """Reconcile the allow-list from a comma-separated player-ID string."""
    set_head_ref_allowlist_ids(tournament, _split_csv_with_blanks(csv))


# ---------------------------------------------------------------------------
# MatchReferee
# ---------------------------------------------------------------------------


def get_match_referee_rows(match: Match) -> list[MatchReferee]:
    """Return ``MatchReferee`` rows for a match, ordered by slot."""
    return MatchReferee.query.filter_by(match_uuid=match.uuid).order_by(MatchReferee.slot).all()


def get_match_ref_team_ids(match: Match) -> list[str]:
    """Resolved team IDs across all referee slots, in slot order.

    ``""`` is returned for slots whose ``team_id`` is not yet resolved.
    Slot positions are preserved by filling gaps from the slot indices.
    """
    rows = get_match_referee_rows(match)
    if not rows:
        return []
    max_slot = rows[-1].slot
    by_slot = {r.slot: r for r in rows}
    return [(by_slot[s].team_id or "") if s in by_slot else "" for s in range(max_slot + 1)]


def get_match_ref_initials(match: Match) -> list[str]:
    """Initial ASS expressions across all referee slots, in slot order."""
    rows = get_match_referee_rows(match)
    if not rows:
        return []
    max_slot = rows[-1].slot
    by_slot = {r.slot: r for r in rows}
    return [(by_slot[s].initial or "") if s in by_slot else "" for s in range(max_slot + 1)]


def get_match_refs_csv(match: Match) -> str:
    """Comma-separated team-ID string, preserving slot positions."""
    return ",".join(get_match_ref_team_ids(match))


def get_match_refs_initial_csv(match: Match) -> str:
    """Comma-separated initial-expression string, preserving slot positions."""
    return ",".join(get_match_ref_initials(match))


def set_match_referees(match: Match, refs: list[str], initials: list[str]) -> None:
    """Reconcile ``MatchReferee`` rows for *match* from parallel team-ID and initial lists.

    The two lists must be parallel; the shorter is padded with ``""`` so
    every position becomes a slot. Slots where both values are empty are
    not stored. ``team_id`` values that don't reference a real team are
    stored as ``None`` and the original expression is kept in ``initial``
    for later resolution.
    """
    n = max(len(refs), len(initials))
    refs = list(refs) + [""] * (n - len(refs))
    initials = list(initials) + [""] * (n - len(initials))

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


def set_match_referees_from_csv(match: Match, refs_csv: str | None, initials_csv: str | None) -> None:
    """Convenience wrapper that splits parallel CSV strings before reconciling."""
    set_match_referees(match, _split_csv_with_blanks(refs_csv), _split_csv_with_blanks(initials_csv))


def clear_match_referees(match: Match) -> None:
    """Delete every ``MatchReferee`` row for *match*."""
    for row in MatchReferee.query.filter_by(match_uuid=match.uuid).all():
        db.session.delete(row)


# ---------------------------------------------------------------------------
# MatchPlayer
# ---------------------------------------------------------------------------


def get_match_player_ids(match: Match, side: WinnerSide) -> list[str]:
    """Return the player IDs registered for *side* on *match*, in insertion order."""
    rows = MatchPlayer.query.filter_by(match_uuid=match.uuid, side=side).order_by(MatchPlayer.id).all()
    return [r.player_id for r in rows]


def set_match_players(match: Match, team1_players: Iterable[str], team2_players: Iterable[str]) -> None:
    """Reconcile ``MatchPlayer`` rows for *match* from per-side player ID lists.

    A player who appears on both sides simultaneously is a data error: the
    side processed first wins and the second is skipped with a warning,
    matching the unique-(match, player) constraint on the destination
    table. Orphan player IDs are skipped with a warning.
    """
    desired: dict[str, WinnerSide] = {}
    for side, ids in (
        (WinnerSide.TEAM1, team1_players),
        (WinnerSide.TEAM2, team2_players),
    ):
        for pid in ids:
            if not pid:
                continue
            if pid in desired and desired[pid] != side:
                logger.warning(
                    "match_players: match=%s player_id=%r appears on both sides; keeping side=%s",
                    match.uuid,
                    pid,
                    desired[pid].value,
                )
                continue
            desired[pid] = side

    if desired:
        present = _existing_ids(Player, Player.id.in_(desired.keys()))
        for orphan in set(desired) - present:
            logger.warning(
                "match_players: match=%s references unknown player_id=%r; skipped",
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


# ---------------------------------------------------------------------------
# CameraTimepoint
# ---------------------------------------------------------------------------


def get_camera_timepoint_arrays(
    camera: Camera,
) -> tuple[list[str | None], list[float | None]]:
    """Return ``(time_world, time_video)`` parallel arrays in sequence order."""
    rows = CameraTimepoint.query.filter_by(camera_uuid=camera.uuid).order_by(CameraTimepoint.sequence).all()
    return [r.time_world for r in rows], [r.time_video for r in rows]


def set_camera_timepoints(camera: Camera, worlds: list, videos: list) -> None:
    """Reconcile ``CameraTimepoint`` rows for *camera* from parallel arrays.

    If the two arrays disagree in length, all destination rows for the
    camera are cleared rather than producing partial or misaligned
    interpolation anchors.
    """
    desired: dict[int, tuple] = {}
    if len(worlds) == len(videos):
        for seq, (tw, tv) in enumerate(zip(worlds, videos)):
            desired[seq] = (tw, tv)
    elif worlds or videos:
        logger.warning(
            "camera_timepoints: camera=%s has mismatched array lengths (world=%d, video=%d); destination rows cleared",
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
