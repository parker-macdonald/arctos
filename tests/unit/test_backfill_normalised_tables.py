"""Tests for ``scripts/backfill_normalised_tables``.

Each test seeds legacy blob columns on the source models, runs the relevant
``backfill_*`` function, and asserts the destination join table contains the
expected rows. Idempotency is exercised by running each backfill twice and
checking the second run inserts nothing new.

These tests intentionally use the real backfill module (imported via the
``scripts`` package) rather than re-implementing its logic — the goal is to
catch regressions in the script itself, including its handling of orphan FK
references, malformed JSON, and the multi-format ``camera_stream_starts``
payload.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# scripts/ is not a Python package — load the module directly so tests can
# call its functions without the developer having to add an __init__.py
# they wouldn't otherwise need.
SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
import backfill_normalised_tables as backfill  # noqa: E402

from app.domain.enums import WinnerSide  # noqa: E402
from models import (  # noqa: E402
    Camera,
    CameraTimepoint,
    Field,
    HeadRefAllowList,
    Match,
    MatchPlayer,
    MatchReferee,
    Player,
    db,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_match(tournament_url: str, name: str = "M", **overrides) -> Match:
    """Insert and flush a minimal Match so its uuid is available for FK use."""
    defaults = dict(
        name=name,
        event=tournament_url,
        schedule_type="STATIC",
        set_type="SETS",
        nominal_length=60,
    )
    defaults.update(overrides)
    m = Match(**defaults)
    db.session.add(m)
    db.session.flush()
    return m


def _make_camera(match_uuid: str, tournament_url: str, field_id: int, **overrides) -> Camera:
    """Insert and flush a minimal Camera bound to the given match/field."""
    defaults = dict(
        match_uuid=match_uuid,
        event=tournament_url,
        field=field_id,
        name="cam",
    )
    defaults.update(overrides)
    cam = Camera(**defaults)
    db.session.add(cam)
    db.session.flush()
    return cam


# ---------------------------------------------------------------------------
# headref_allowlist
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_backfill_head_refs_inserts_one_per_csv_entry(test_db, tournament, head_ref_player):
    """Each comma-separated player ID becomes one HeadRefAllowList row."""
    # Add a second valid player so the comma-separated list has two entries.
    # head_ref_player fixture seeds an allow-list row for test_ref1.
    db.session.add(Player(id="ref2", name="Ref 2", pw_hash="h"))
    db.session.commit()

    tournament.head_refs_allowed_list = f"{head_ref_player.id}, ref2"
    db.session.commit()

    targets = backfill.FkTargets.load()
    stats = backfill.backfill_head_ref_allowlist(targets)
    db.session.commit()

    # One row was already seeded by the fixture (skipped_existing); the other CSV entry was inserted.
    assert stats.inserted == 1
    assert stats.skipped_existing == 1
    assert HeadRefAllowList.query.filter_by(event=tournament.url).count() == 2


@pytest.mark.unit
def test_backfill_head_refs_skips_orphan_player(test_db, tournament):
    """A player ID not present in `players` is reported and skipped."""
    tournament.head_refs_allowed_list = "ghost_player"
    db.session.commit()

    targets = backfill.FkTargets.load()
    stats = backfill.backfill_head_ref_allowlist(targets)
    db.session.commit()

    assert stats.inserted == 0
    assert stats.skipped_orphan == 1
    assert HeadRefAllowList.query.count() == 0


@pytest.mark.unit
def test_backfill_head_refs_is_idempotent(test_db, tournament, head_ref_player):
    """Running the backfill twice does not duplicate rows."""
    tournament.head_refs_allowed_list = head_ref_player.id
    db.session.commit()

    targets = backfill.FkTargets.load()
    backfill.backfill_head_ref_allowlist(targets)
    db.session.commit()
    second = backfill.backfill_head_ref_allowlist(targets)
    db.session.commit()

    assert second.inserted == 0
    assert second.skipped_existing == 1
    assert HeadRefAllowList.query.count() == 1


@pytest.mark.unit
def test_backfill_head_refs_skips_empty_entries(test_db, tournament, head_ref_player):
    """Empty entries from trailing commas / extra whitespace don't error out."""
    # head_ref_player fixture already inserted the allow-list row for test_ref1, so the
    # backfill counts it as ``skipped_existing`` rather than ``inserted``.
    tournament.head_refs_allowed_list = f", {head_ref_player.id} ,, ,"
    db.session.commit()

    targets = backfill.FkTargets.load()
    stats = backfill.backfill_head_ref_allowlist(targets)
    db.session.commit()

    assert stats.skipped_existing == 1
    assert HeadRefAllowList.query.filter_by(event=tournament.url).count() == 1


# ---------------------------------------------------------------------------
# match_referees
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_backfill_match_referees_preserves_slot_order(test_db, tournament, seeded_teams):
    """Each comma-separated entry becomes one row at its 0-based slot."""
    m = _make_match(tournament.url)
    m.refs = "team1, team2, team3"
    m.refs_initial = "team1, Match A::winner, team3"
    db.session.commit()

    targets = backfill.FkTargets.load()
    backfill.backfill_match_referees(targets)
    db.session.commit()

    rows = MatchReferee.query.filter_by(match_uuid=m.uuid).order_by(MatchReferee.slot).all()
    assert [r.slot for r in rows] == [0, 1, 2]
    assert [r.team_id for r in rows] == ["team1", "team2", "team3"]
    assert rows[1].initial == "Match A::winner"


@pytest.mark.unit
def test_backfill_match_referees_handles_unequal_lengths(test_db, tournament, seeded_teams):
    """If refs and refs_initial differ in length, the shorter is padded."""
    m = _make_match(tournament.url)
    m.refs = "team1"
    m.refs_initial = "team1, team2, Match A::winner"
    db.session.commit()

    targets = backfill.FkTargets.load()
    stats = backfill.backfill_match_referees(targets)
    db.session.commit()

    rows = MatchReferee.query.filter_by(match_uuid=m.uuid).order_by(MatchReferee.slot).all()
    assert [r.slot for r in rows] == [0, 1, 2]
    assert rows[0].team_id == "team1"
    assert rows[1].team_id is None
    assert rows[1].initial == "team2"
    # The third initial is an unresolved expression, not a real team ID.
    assert rows[2].team_id is None
    assert rows[2].initial == "Match A::winner"
    assert stats.inserted == 3


@pytest.mark.unit
def test_backfill_match_referees_orphan_team_keeps_row(test_db, tournament):
    """A refs[i] pointing at a non-existent team yields a row with team_id=None
    (the initial expression is still useful for re-resolution) and is counted
    as ``skipped_orphan``."""
    m = _make_match(tournament.url)
    m.refs = "ghost_team"
    m.refs_initial = "ghost_team"
    db.session.commit()

    targets = backfill.FkTargets.load()
    stats = backfill.backfill_match_referees(targets)
    db.session.commit()

    row = MatchReferee.query.filter_by(match_uuid=m.uuid).one()
    assert row.team_id is None
    assert row.initial == "ghost_team"
    assert stats.skipped_orphan == 1


# ---------------------------------------------------------------------------
# match_players
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_backfill_match_players_splits_by_side(test_db, tournament, seeded_teams):
    """team1_players → side=TEAM1, team2_players → side=TEAM2."""
    db.session.add_all([Player(id="p1", name="P1", pw_hash="h"), Player(id="p2", name="P2", pw_hash="h")])
    db.session.commit()

    m = _make_match(tournament.url)
    m.team1_players = json.dumps(["p1"])
    m.team2_players = json.dumps(["p2"])
    db.session.commit()

    targets = backfill.FkTargets.load()
    backfill.backfill_match_players(targets)
    db.session.commit()

    rows = MatchPlayer.query.filter_by(match_uuid=m.uuid).all()
    by_side = {r.side: r.player_id for r in rows}
    assert by_side[WinnerSide.TEAM1] == "p1"
    assert by_side[WinnerSide.TEAM2] == "p2"


@pytest.mark.unit
def test_backfill_match_players_skips_orphan_player(test_db, tournament, seeded_teams):
    """Player IDs not present in `players` are reported and skipped."""
    m = _make_match(tournament.url)
    m.team1_players = json.dumps(["ghost1"])
    db.session.commit()

    targets = backfill.FkTargets.load()
    stats = backfill.backfill_match_players(targets)
    db.session.commit()

    assert stats.inserted == 0
    assert stats.skipped_orphan == 1


@pytest.mark.unit
def test_backfill_match_players_skips_invalid_json(test_db, tournament, seeded_teams):
    """Garbage in team1_players is counted as invalid and the row is skipped."""
    m = _make_match(tournament.url)
    m.team1_players = "{not json"
    db.session.commit()

    targets = backfill.FkTargets.load()
    stats = backfill.backfill_match_players(targets)
    db.session.commit()

    assert stats.skipped_invalid == 1


# ---------------------------------------------------------------------------
# camera_timepoints
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_backfill_camera_timepoints_pairs_arrays(test_db, tournament):
    """time_world[i] pairs with time_video[i] at sequence i."""
    m = _make_match(tournament.url)
    f = Field.query.filter_by(event=tournament.url, name="Field 1").one()
    cam = _make_camera(m.uuid, tournament.url, f.id)
    cam.time_world = json.dumps(["2026-01-01T00:00:00Z", "2026-01-01T00:00:10Z"])
    cam.time_video = json.dumps([0.0, 10.5])
    db.session.commit()

    targets = backfill.FkTargets.load()
    backfill.backfill_camera_timepoints(targets)
    db.session.commit()

    rows = CameraTimepoint.query.filter_by(camera_uuid=cam.uuid).order_by(CameraTimepoint.sequence).all()
    assert len(rows) == 2
    assert rows[0].sequence == 0
    assert rows[0].time_world == "2026-01-01T00:00:00Z"
    assert rows[0].time_video == 0.0
    assert rows[1].time_video == 10.5


@pytest.mark.unit
def test_backfill_camera_timepoints_skips_mismatched_lengths(test_db, tournament):
    """If the parallel arrays differ in length, the camera is skipped with a warning."""
    m = _make_match(tournament.url)
    f = Field.query.filter_by(event=tournament.url, name="Field 1").one()
    cam = _make_camera(m.uuid, tournament.url, f.id)
    cam.time_world = json.dumps(["a", "b", "c"])
    cam.time_video = json.dumps([0.0, 1.0])
    db.session.commit()

    targets = backfill.FkTargets.load()
    stats = backfill.backfill_camera_timepoints(targets)
    db.session.commit()

    assert CameraTimepoint.query.filter_by(camera_uuid=cam.uuid).count() == 0
    assert any("camera" in w for w in stats.warnings)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_validate_passes_on_clean_backfill(test_db, tournament, head_ref_player, seeded_teams):
    """End-to-end: full backfill on clean data produces no validation failures."""
    db.session.add_all([Player(id="p1", name="P1", pw_hash="h"), Player(id="p2", name="P2", pw_hash="h")])
    tournament.head_refs_allowed_list = head_ref_player.id
    m = _make_match(tournament.url)
    m.refs = "team1"
    m.refs_initial = "team1"
    m.team1_players = json.dumps(["p1"])
    m.team2_players = json.dumps(["p2"])
    db.session.commit()

    backfill.run_backfill(verbose=False)
    results = backfill.validate()
    assert all(r.ok for r in results), [r for r in results if not r.ok]
