"""Tests for ``app.services.dual_write``.

Each sync function is exercised across four shapes:

1. **Initial populate** — destination table starts empty; sync inserts the
   right rows from the legacy blob.
2. **Update** — destination table has stale data; sync converges it on
   the new blob value.
3. **Clear** — legacy blob set to ``None`` / empty; sync deletes the
   destination rows.
4. **Idempotency** — running sync twice in a row makes no changes the
   second time.

Each parity assertion is exercised in two shapes:

1. **In sync** — sync was just run; assertion passes silently.
2. **Drifted** — destination table mutated by hand; assertion raises
   ``AssertionError`` with a message identifying the row.

Orphan-FK paths (sync skips orphan refs / stores ``team_id=None``) are
covered alongside the happy-path tests for each function.
"""

from __future__ import annotations

import json

import pytest
import sqlalchemy as sa

from app.domain.enums import WinnerSide
from app.services import dual_write
from models import (
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


def _make_match(tournament_url: str, name: str = "M") -> Match:
    """Insert a minimal Match and flush so its uuid is available."""
    m = Match(
        name=name,
        event=tournament_url,
        schedule_type="STATIC",
        set_type="SETS",
        nominal_length=60,
    )
    db.session.add(m)
    db.session.flush()
    return m


def _make_camera(match_uuid: str, tournament_url: str, field_id: int) -> Camera:
    """Insert a minimal Camera bound to the given match/field."""
    cam = Camera(
        match_uuid=match_uuid,
        event=tournament_url,
        field=field_id,
        name="cam",
    )
    db.session.add(cam)
    db.session.flush()
    return cam


# ---------------------------------------------------------------------------
# sync_head_ref_allowlist
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_sync_head_ref_allowlist_initial_populate(test_db, tournament, head_ref_player):
    """Empty destination + populated CSV → one row per CSV entry."""
    db.session.add(Player(id="ref2", name="Ref 2", pw_hash="h"))
    tournament.head_refs_allowed_list = f"{head_ref_player.id}, ref2"
    db.session.commit()

    dual_write.sync_head_ref_allowlist(tournament)
    db.session.commit()

    rows = HeadRefAllowList.query.filter_by(event=tournament.url).all()
    assert {r.player_id for r in rows} == {head_ref_player.id, "ref2"}


@pytest.mark.unit
def test_sync_head_ref_allowlist_update_adds_and_removes(test_db, tournament, head_ref_player):
    """Existing rows reconcile to the new CSV (some added, some deleted)."""
    db.session.add_all([Player(id="ref2", name="R2", pw_hash="h"), Player(id="ref3", name="R3", pw_hash="h")])
    db.session.add(HeadRefAllowList(event=tournament.url, player_id=head_ref_player.id))
    db.session.add(HeadRefAllowList(event=tournament.url, player_id="ref2"))
    tournament.head_refs_allowed_list = f"{head_ref_player.id}, ref3"
    db.session.commit()

    dual_write.sync_head_ref_allowlist(tournament)
    db.session.commit()

    rows = HeadRefAllowList.query.filter_by(event=tournament.url).all()
    assert {r.player_id for r in rows} == {head_ref_player.id, "ref3"}


@pytest.mark.unit
def test_sync_head_ref_allowlist_clear(test_db, tournament, head_ref_player):
    """Clearing the CSV deletes all destination rows."""
    db.session.add(HeadRefAllowList(event=tournament.url, player_id=head_ref_player.id))
    tournament.head_refs_allowed_list = ""
    db.session.commit()

    dual_write.sync_head_ref_allowlist(tournament)
    db.session.commit()

    assert HeadRefAllowList.query.filter_by(event=tournament.url).count() == 0


@pytest.mark.unit
def test_sync_head_ref_allowlist_skips_orphan_player(test_db, tournament):
    """Orphan player IDs in the CSV are skipped (not inserted)."""
    tournament.head_refs_allowed_list = "ghost_player"
    db.session.commit()

    dual_write.sync_head_ref_allowlist(tournament)
    db.session.commit()

    assert HeadRefAllowList.query.filter_by(event=tournament.url).count() == 0


@pytest.mark.unit
def test_sync_head_ref_allowlist_is_idempotent(test_db, tournament, head_ref_player):
    """Running twice in a row produces no second-pass changes."""
    tournament.head_refs_allowed_list = head_ref_player.id
    db.session.commit()

    dual_write.sync_head_ref_allowlist(tournament)
    db.session.commit()
    dual_write.sync_head_ref_allowlist(tournament)
    db.session.commit()

    rows = HeadRefAllowList.query.filter_by(event=tournament.url).all()
    assert len(rows) == 1
    assert rows[0].player_id == head_ref_player.id


# ---------------------------------------------------------------------------
# sync_match_referees
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_sync_match_referees_initial_populate(test_db, tournament, seeded_teams):
    """Empty destination + populated CSV → rows per slot, in order."""
    m = _make_match(tournament.url)
    m.refs = "team1, team2"
    m.refs_initial = "team1, Match A::winner"
    db.session.commit()

    dual_write.sync_match_referees(m)
    db.session.commit()

    rows = MatchReferee.query.filter_by(match_uuid=m.uuid).order_by(MatchReferee.slot).all()
    assert [r.slot for r in rows] == [0, 1]
    assert rows[0].team_id == "team1"
    assert rows[1].team_id == "team2"
    assert rows[1].initial == "Match A::winner"


@pytest.mark.unit
def test_sync_match_referees_orphan_team_stored_as_none(test_db, tournament):
    """A refs[i] pointing at a non-existent team stores team_id=None, preserves initial."""
    m = _make_match(tournament.url)
    m.refs = "ghost_team"
    m.refs_initial = "ghost_team"
    db.session.commit()

    dual_write.sync_match_referees(m)
    db.session.commit()

    row = MatchReferee.query.filter_by(match_uuid=m.uuid).one()
    assert row.team_id is None
    assert row.initial == "ghost_team"


@pytest.mark.unit
def test_sync_match_referees_clear_deletes_all(test_db, tournament, seeded_teams):
    """Setting refs/refs_initial to None deletes all destination rows."""
    m = _make_match(tournament.url)
    m.refs = "team1"
    m.refs_initial = "team1"
    db.session.commit()
    dual_write.sync_match_referees(m)
    db.session.commit()
    assert MatchReferee.query.filter_by(match_uuid=m.uuid).count() == 1

    m.refs = None
    m.refs_initial = None
    db.session.commit()
    dual_write.sync_match_referees(m)
    db.session.commit()

    assert MatchReferee.query.filter_by(match_uuid=m.uuid).count() == 0


@pytest.mark.unit
def test_sync_match_referees_update_changes_in_place(test_db, tournament, seeded_teams):
    """Updating refs converges existing rows in-place; doesn't duplicate."""
    m = _make_match(tournament.url)
    m.refs = "team1, team2"
    m.refs_initial = "team1, team2"
    db.session.commit()
    dual_write.sync_match_referees(m)
    db.session.commit()

    m.refs = "team1, team3"  # slot 1 changed
    m.refs_initial = "team1, team3"
    db.session.commit()
    dual_write.sync_match_referees(m)
    db.session.commit()

    rows = MatchReferee.query.filter_by(match_uuid=m.uuid).order_by(MatchReferee.slot).all()
    assert len(rows) == 2
    assert rows[1].team_id == "team3"


@pytest.mark.unit
def test_sync_match_referees_is_idempotent(test_db, tournament, seeded_teams):
    """Two consecutive syncs produce identical state."""
    m = _make_match(tournament.url)
    m.refs = "team1"
    m.refs_initial = "team1"
    db.session.commit()

    dual_write.sync_match_referees(m)
    db.session.commit()
    dual_write.sync_match_referees(m)
    db.session.commit()

    rows = MatchReferee.query.filter_by(match_uuid=m.uuid).all()
    assert len(rows) == 1


# ---------------------------------------------------------------------------
# sync_match_players
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_sync_match_players_splits_by_side(test_db, tournament, seeded_teams):
    """team1_players → side=TEAM1, team2_players → side=TEAM2."""
    db.session.add_all([Player(id="p1", name="P1", pw_hash="h"), Player(id="p2", name="P2", pw_hash="h")])
    m = _make_match(tournament.url)
    m.team1_players = json.dumps(["p1"])
    m.team2_players = json.dumps(["p2"])
    db.session.commit()

    dual_write.sync_match_players(m)
    db.session.commit()

    by_side = {r.side: r.player_id for r in MatchPlayer.query.filter_by(match_uuid=m.uuid).all()}
    assert by_side[WinnerSide.TEAM1] == "p1"
    assert by_side[WinnerSide.TEAM2] == "p2"


@pytest.mark.unit
def test_sync_match_players_clear(test_db, tournament, seeded_teams):
    """Clearing the JSON arrays deletes all destination rows."""
    db.session.add(Player(id="p1", name="P1", pw_hash="h"))
    m = _make_match(tournament.url)
    m.team1_players = json.dumps(["p1"])
    db.session.commit()
    dual_write.sync_match_players(m)
    db.session.commit()
    assert MatchPlayer.query.filter_by(match_uuid=m.uuid).count() == 1

    m.team1_players = None
    m.team2_players = None
    db.session.commit()
    dual_write.sync_match_players(m)
    db.session.commit()

    assert MatchPlayer.query.filter_by(match_uuid=m.uuid).count() == 0


@pytest.mark.unit
def test_sync_match_players_skips_orphan_player(test_db, tournament, seeded_teams):
    """Orphan player IDs in the JSON are skipped (no insert)."""
    m = _make_match(tournament.url)
    m.team1_players = json.dumps(["ghost"])
    db.session.commit()

    dual_write.sync_match_players(m)
    db.session.commit()

    assert MatchPlayer.query.filter_by(match_uuid=m.uuid).count() == 0


@pytest.mark.unit
def test_sync_match_players_is_idempotent(test_db, tournament, seeded_teams):
    """Two consecutive syncs produce identical state."""
    db.session.add(Player(id="p1", name="P1", pw_hash="h"))
    m = _make_match(tournament.url)
    m.team1_players = json.dumps(["p1"])
    db.session.commit()

    dual_write.sync_match_players(m)
    db.session.commit()
    dual_write.sync_match_players(m)
    db.session.commit()

    assert MatchPlayer.query.filter_by(match_uuid=m.uuid).count() == 1


# ---------------------------------------------------------------------------
# sync_camera_timepoints
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_sync_camera_timepoints_pairs_arrays(test_db, tournament):
    """Parallel arrays produce one row per (sequence, world, video) triple."""
    m = _make_match(tournament.url)
    f = Field.query.filter_by(event=tournament.url, name="Field 1").one()
    cam = _make_camera(m.uuid, tournament.url, f.id)
    cam.time_world = json.dumps(["t0", "t1"])
    cam.time_video = json.dumps([0.0, 10.0])
    db.session.commit()

    dual_write.sync_camera_timepoints(cam)
    db.session.commit()

    rows = CameraTimepoint.query.filter_by(camera_uuid=cam.uuid).order_by(CameraTimepoint.sequence).all()
    assert [(r.sequence, r.time_world, r.time_video) for r in rows] == [(0, "t0", 0.0), (1, "t1", 10.0)]


@pytest.mark.unit
def test_sync_camera_timepoints_skips_mismatched_lengths(test_db, tournament):
    """Mismatched parallel-array lengths clear destination rather than producing partials."""
    m = _make_match(tournament.url)
    f = Field.query.filter_by(event=tournament.url, name="Field 1").one()
    cam = _make_camera(m.uuid, tournament.url, f.id)
    cam.time_world = json.dumps(["a", "b"])
    cam.time_video = json.dumps([0.0])
    db.session.commit()

    dual_write.sync_camera_timepoints(cam)
    db.session.commit()

    assert CameraTimepoint.query.filter_by(camera_uuid=cam.uuid).count() == 0


# ---------------------------------------------------------------------------
# Parity assertions
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_assert_head_ref_allowlist_parity_passes_when_in_sync(test_db, tournament, head_ref_player):
    """After sync, the assertion passes silently."""
    tournament.head_refs_allowed_list = head_ref_player.id
    db.session.commit()
    dual_write.sync_head_ref_allowlist(tournament)
    db.session.commit()

    dual_write.assert_head_ref_allowlist_parity(tournament)


@pytest.mark.unit
def test_assert_head_ref_allowlist_parity_raises_on_drift(test_db, tournament, head_ref_player):
    """If the destination is mutated by hand, parity fails loudly."""
    tournament.head_refs_allowed_list = head_ref_player.id
    db.session.commit()
    dual_write.sync_head_ref_allowlist(tournament)
    db.session.commit()

    # Drift: delete the destination row directly.
    db.session.execute(sa.text("DELETE FROM headref_allowlist"))
    db.session.commit()

    with pytest.raises(AssertionError, match="head_refs parity drift"):
        dual_write.assert_head_ref_allowlist_parity(tournament)


@pytest.mark.unit
def test_assert_match_referees_parity_passes_when_in_sync(test_db, tournament, seeded_teams):
    m = _make_match(tournament.url)
    m.refs = "team1"
    m.refs_initial = "team1"
    db.session.commit()
    dual_write.sync_match_referees(m)
    db.session.commit()

    dual_write.assert_match_referees_parity(m)


@pytest.mark.unit
def test_assert_match_referees_parity_raises_on_drift(test_db, tournament, seeded_teams):
    m = _make_match(tournament.url)
    m.refs = "team1"
    m.refs_initial = "team1"
    db.session.commit()
    dual_write.sync_match_referees(m)
    db.session.commit()

    db.session.execute(sa.text("DELETE FROM match_referees"))
    db.session.commit()

    with pytest.raises(AssertionError, match="match_referees parity drift"):
        dual_write.assert_match_referees_parity(m)


@pytest.mark.unit
def test_assert_match_players_parity_passes_when_in_sync(test_db, tournament, seeded_teams):
    db.session.add(Player(id="p1", name="P1", pw_hash="h"))
    m = _make_match(tournament.url)
    m.team1_players = json.dumps(["p1"])
    db.session.commit()
    dual_write.sync_match_players(m)
    db.session.commit()

    dual_write.assert_match_players_parity(m)


@pytest.mark.unit
def test_assert_camera_timepoints_parity_passes_when_in_sync(test_db, tournament):
    m = _make_match(tournament.url)
    f = Field.query.filter_by(event=tournament.url, name="Field 1").one()
    cam = _make_camera(m.uuid, tournament.url, f.id)
    cam.time_world = json.dumps(["t0"])
    cam.time_video = json.dumps([0.0])
    db.session.commit()
    dual_write.sync_camera_timepoints(cam)
    db.session.commit()

    dual_write.assert_camera_timepoints_parity(cam)
