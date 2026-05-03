"""Tests for ``app.services.dual_write``.

Each ``set_*`` writer is exercised across four shapes:

1. **Initial populate** — destination table starts empty; the writer inserts
   the right rows from the parsed input.
2. **Update** — destination table already has rows; the writer converges them
   to the new desired state (insert / update / delete).
3. **Clear** — input is empty; the writer removes every row.
4. **Idempotency** — running the writer twice in a row makes no changes the
   second time.

Each ``get_*`` reader is exercised against in-table data inserted by the
matching writer to confirm round-trip behaviour.

Orphan-FK paths (writer skips orphan refs / stores ``team_id=None``) are
covered alongside the happy-path tests for each function.
"""

from __future__ import annotations

import pytest

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
# HeadRefAllowList
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_set_head_ref_allowlist_initial_populate(test_db, tournament, head_ref_player):
    """Empty destination + new IDs → one row per ID."""
    db.session.add(Player(id="ref2", name="Ref 2", pw_hash="h"))

    dual_write.set_head_ref_allowlist_ids(tournament, [head_ref_player.id, "ref2"])
    db.session.commit()

    rows = HeadRefAllowList.query.filter_by(event=tournament.url).all()
    assert {r.player_id for r in rows} == {head_ref_player.id, "ref2"}


@pytest.mark.unit
def test_set_head_ref_allowlist_update_adds_and_removes(test_db, tournament, head_ref_player):
    """Existing rows reconcile to the new ID set (some added, some removed)."""
    # head_ref_player fixture seeds an allow-list row for test_ref1.
    db.session.add_all([Player(id="ref2", name="R2", pw_hash="h"), Player(id="ref3", name="R3", pw_hash="h")])
    db.session.add(HeadRefAllowList(event=tournament.url, player_id="ref2"))

    dual_write.set_head_ref_allowlist_ids(tournament, [head_ref_player.id, "ref3"])
    db.session.commit()

    rows = HeadRefAllowList.query.filter_by(event=tournament.url).all()
    assert {r.player_id for r in rows} == {head_ref_player.id, "ref3"}


@pytest.mark.unit
def test_set_head_ref_allowlist_clear(test_db, tournament, head_ref_player):
    """Empty input deletes all destination rows."""
    # head_ref_player fixture already seeded an allow-list row.
    dual_write.set_head_ref_allowlist_ids(tournament, [])
    db.session.commit()

    assert HeadRefAllowList.query.filter_by(event=tournament.url).count() == 0


@pytest.mark.unit
def test_set_head_ref_allowlist_skips_orphan_player(test_db, tournament):
    """Orphan player IDs are skipped (not inserted)."""
    dual_write.set_head_ref_allowlist_ids(tournament, ["ghost_player"])
    db.session.commit()

    assert HeadRefAllowList.query.filter_by(event=tournament.url).count() == 0


@pytest.mark.unit
def test_set_head_ref_allowlist_is_idempotent(test_db, tournament, head_ref_player):
    """Running twice produces no second-pass changes."""
    dual_write.set_head_ref_allowlist_ids(tournament, [head_ref_player.id])
    db.session.commit()
    dual_write.set_head_ref_allowlist_ids(tournament, [head_ref_player.id])
    db.session.commit()

    rows = HeadRefAllowList.query.filter_by(event=tournament.url).all()
    assert len(rows) == 1
    assert rows[0].player_id == head_ref_player.id


@pytest.mark.unit
def test_set_head_ref_allowlist_from_csv_splits(test_db, tournament, head_ref_player):
    """The CSV convenience wrapper splits and reconciles."""
    db.session.add(Player(id="ref2", name="R2", pw_hash="h"))
    dual_write.set_head_ref_allowlist_from_csv(tournament, f"{head_ref_player.id}, ref2")
    db.session.commit()

    assert set(dual_write.get_head_ref_allowlist_ids(tournament)) == {head_ref_player.id, "ref2"}


# ---------------------------------------------------------------------------
# MatchReferee
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_set_match_referees_initial_populate(test_db, tournament, seeded_teams):
    """Initial populate inserts one row per slot, in order."""
    m = _make_match(tournament.url)
    dual_write.set_match_referees(m, ["team1", "team2"], ["team1", "Match A::winner"])
    db.session.commit()

    rows = MatchReferee.query.filter_by(match_uuid=m.uuid).order_by(MatchReferee.slot).all()
    assert [r.slot for r in rows] == [0, 1]
    assert rows[0].team_id == "team1"
    assert rows[1].team_id == "team2"
    assert rows[1].initial == "Match A::winner"


@pytest.mark.unit
def test_set_match_referees_orphan_team_stored_as_none(test_db, tournament):
    """Refs[i] pointing at a non-existent team stores team_id=None, preserves initial."""
    m = _make_match(tournament.url)
    dual_write.set_match_referees(m, ["ghost_team"], ["ghost_team"])
    db.session.commit()

    row = MatchReferee.query.filter_by(match_uuid=m.uuid).one()
    assert row.team_id is None
    assert row.initial == "ghost_team"


@pytest.mark.unit
def test_set_match_referees_update_changes_in_place(test_db, tournament, seeded_teams):
    """Updating refs converges existing rows in-place; doesn't duplicate."""
    m = _make_match(tournament.url)
    dual_write.set_match_referees(m, ["team1", "team2"], ["team1", "team2"])
    db.session.commit()

    dual_write.set_match_referees(m, ["team1", "team3"], ["team1", "team3"])
    db.session.commit()

    rows = MatchReferee.query.filter_by(match_uuid=m.uuid).order_by(MatchReferee.slot).all()
    assert len(rows) == 2
    assert rows[1].team_id == "team3"


@pytest.mark.unit
def test_set_match_referees_clear_via_empty_lists(test_db, tournament, seeded_teams):
    """Empty input lists delete all slots."""
    m = _make_match(tournament.url)
    dual_write.set_match_referees(m, ["team1"], ["team1"])
    db.session.commit()

    dual_write.set_match_referees(m, [], [])
    db.session.commit()

    assert MatchReferee.query.filter_by(match_uuid=m.uuid).count() == 0


@pytest.mark.unit
def test_clear_match_referees_deletes_all(test_db, tournament, seeded_teams):
    """``clear_match_referees`` deletes every slot for the match."""
    m = _make_match(tournament.url)
    dual_write.set_match_referees(m, ["team1", "team2"], ["team1", "team2"])
    db.session.commit()

    dual_write.clear_match_referees(m)
    db.session.commit()

    assert MatchReferee.query.filter_by(match_uuid=m.uuid).count() == 0


@pytest.mark.unit
def test_set_match_referees_is_idempotent(test_db, tournament, seeded_teams):
    """Two consecutive writes produce identical state."""
    m = _make_match(tournament.url)
    dual_write.set_match_referees(m, ["team1"], ["team1"])
    db.session.commit()
    dual_write.set_match_referees(m, ["team1"], ["team1"])
    db.session.commit()

    rows = MatchReferee.query.filter_by(match_uuid=m.uuid).all()
    assert len(rows) == 1


@pytest.mark.unit
def test_set_match_referees_from_csv_round_trip(test_db, tournament, seeded_teams):
    """CSV convenience wrapper splits parallel strings consistently."""
    m = _make_match(tournament.url)
    dual_write.set_match_referees_from_csv(m, "team1,team2", "team1,Match X::winner")
    db.session.commit()

    assert dual_write.get_match_ref_team_ids(m) == ["team1", "team2"]
    assert dual_write.get_match_ref_initials(m) == ["team1", "Match X::winner"]
    assert dual_write.get_match_refs_csv(m) == "team1,team2"
    assert dual_write.get_match_refs_initial_csv(m) == "team1,Match X::winner"


@pytest.mark.unit
def test_get_match_refs_csv_preserves_empty_slot_positions(test_db, tournament, seeded_teams):
    """Empty interior slots are preserved as ``""`` when reconstructing the CSV."""
    m = _make_match(tournament.url)
    db.session.add_all(
        [
            MatchReferee(match_uuid=m.uuid, slot=0, team_id="team1", initial="team1"),
            MatchReferee(match_uuid=m.uuid, slot=2, team_id="team2", initial="team2"),
        ]
    )
    db.session.commit()

    assert dual_write.get_match_ref_team_ids(m) == ["team1", "", "team2"]
    assert dual_write.get_match_refs_csv(m) == "team1,,team2"


# ---------------------------------------------------------------------------
# MatchPlayer
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_set_match_players_splits_by_side(test_db, tournament, seeded_teams):
    """team1_players → side=TEAM1, team2_players → side=TEAM2."""
    db.session.add_all([Player(id="p1", name="P1", pw_hash="h"), Player(id="p2", name="P2", pw_hash="h")])
    m = _make_match(tournament.url)

    dual_write.set_match_players(m, ["p1"], ["p2"])
    db.session.commit()

    by_side = {r.side: r.player_id for r in MatchPlayer.query.filter_by(match_uuid=m.uuid).all()}
    assert by_side[WinnerSide.TEAM1] == "p1"
    assert by_side[WinnerSide.TEAM2] == "p2"


@pytest.mark.unit
def test_set_match_players_clear(test_db, tournament, seeded_teams):
    """Empty inputs delete all destination rows."""
    db.session.add(Player(id="p1", name="P1", pw_hash="h"))
    m = _make_match(tournament.url)
    dual_write.set_match_players(m, ["p1"], [])
    db.session.commit()
    assert MatchPlayer.query.filter_by(match_uuid=m.uuid).count() == 1

    dual_write.set_match_players(m, [], [])
    db.session.commit()

    assert MatchPlayer.query.filter_by(match_uuid=m.uuid).count() == 0


@pytest.mark.unit
def test_set_match_players_skips_orphan_player(test_db, tournament, seeded_teams):
    """Orphan player IDs in the input are skipped (no insert)."""
    m = _make_match(tournament.url)
    dual_write.set_match_players(m, ["ghost"], [])
    db.session.commit()

    assert MatchPlayer.query.filter_by(match_uuid=m.uuid).count() == 0


@pytest.mark.unit
def test_set_match_players_is_idempotent(test_db, tournament, seeded_teams):
    """Two consecutive writes produce identical state."""
    db.session.add(Player(id="p1", name="P1", pw_hash="h"))
    m = _make_match(tournament.url)

    dual_write.set_match_players(m, ["p1"], [])
    db.session.commit()
    dual_write.set_match_players(m, ["p1"], [])
    db.session.commit()

    assert MatchPlayer.query.filter_by(match_uuid=m.uuid).count() == 1


@pytest.mark.unit
def test_get_match_player_ids_preserves_insertion_order(test_db, tournament, seeded_teams):
    """``get_match_player_ids`` returns IDs in the order rows were inserted."""
    db.session.add_all(
        [
            Player(id="p1", name="P1", pw_hash="h"),
            Player(id="p2", name="P2", pw_hash="h"),
            Player(id="p3", name="P3", pw_hash="h"),
        ]
    )
    m = _make_match(tournament.url)
    dual_write.set_match_players(m, ["p1", "p3"], ["p2"])
    db.session.commit()

    assert dual_write.get_match_player_ids(m, WinnerSide.TEAM1) == ["p1", "p3"]
    assert dual_write.get_match_player_ids(m, WinnerSide.TEAM2) == ["p2"]


# ---------------------------------------------------------------------------
# CameraTimepoint
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_set_camera_timepoints_pairs_arrays(test_db, tournament):
    """Parallel arrays produce one row per (sequence, world, video) triple."""
    m = _make_match(tournament.url)
    f = Field.query.filter_by(event=tournament.url, name="Field 1").one()
    cam = _make_camera(m.uuid, tournament.url, f.id)

    dual_write.set_camera_timepoints(cam, ["t0", "t1"], [0.0, 10.0])
    db.session.commit()

    rows = CameraTimepoint.query.filter_by(camera_uuid=cam.uuid).order_by(CameraTimepoint.sequence).all()
    assert [(r.sequence, r.time_world, r.time_video) for r in rows] == [
        (0, "t0", 0.0),
        (1, "t1", 10.0),
    ]


@pytest.mark.unit
def test_set_camera_timepoints_skips_mismatched_lengths(test_db, tournament):
    """Mismatched parallel-array lengths clear destination rather than producing partials."""
    m = _make_match(tournament.url)
    f = Field.query.filter_by(event=tournament.url, name="Field 1").one()
    cam = _make_camera(m.uuid, tournament.url, f.id)

    dual_write.set_camera_timepoints(cam, ["a", "b"], [0.0])
    db.session.commit()

    assert CameraTimepoint.query.filter_by(camera_uuid=cam.uuid).count() == 0


@pytest.mark.unit
def test_get_camera_timepoint_arrays_round_trip(test_db, tournament):
    """``get_camera_timepoint_arrays`` reads back what was written, in sequence order."""
    m = _make_match(tournament.url)
    f = Field.query.filter_by(event=tournament.url, name="Field 1").one()
    cam = _make_camera(m.uuid, tournament.url, f.id)
    dual_write.set_camera_timepoints(cam, ["t0", "t1"], [0.0, 5.0])
    db.session.commit()

    worlds, videos = dual_write.get_camera_timepoint_arrays(cam)
    assert worlds == ["t0", "t1"]
    assert videos == [0.0, 5.0]
