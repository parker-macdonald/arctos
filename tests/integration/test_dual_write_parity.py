"""End-to-end tests that exercise real HTTP routes and verify the
normalised join tables are populated correctly when the relevant route
runs.

Per join-table, this module picks one route that genuinely writes the
table at runtime, drives it through the test client, then queries the
table to confirm the rows landed as expected.

These tests are integration-marked because they go through the full
Flask request/response stack and hit the database, not just the model
layer.
"""

from __future__ import annotations

import pytest

from app.domain.enums import MatchStatus, WinnerSide
from app.services import dual_write
from models import Match, db
from tests.utils import login_as


@pytest.mark.integration
def test_start_match_route_populates_match_players(app, client, tournament, head_ref_player, seeded_teams):
    """``POST /_api/<event>/start-match`` should populate ``match_players``."""
    with app.app_context():
        t = db.session.merge(tournament)
        ref = db.session.merge(head_ref_player)
        from models import Player

        for pid in ("p1", "p2", "p3"):
            db.session.add(Player(id=pid, name=pid, pw_hash="h"))
        tournament_url = t.url
        login_as(client, ref)

        m = Match(
            name="Roster Match",
            event=tournament_url,
            schedule_type="SAFE",
            set_type="SETS",
            status=MatchStatus.READY_TO_START,
            nominal_length=60,
            field="Field 1",
            team1="team1",
            team2="team2",
        )
        db.session.add(m)
        db.session.commit()
        match_id = m.uuid

    resp = client.post(
        f"/_api/{tournament_url}/start-match",
        data={
            "match_id": match_id,
            "team1_players": "p1,p2",
            "team2_players": "p3",
            "match_notes": "",
        },
    )
    assert resp.status_code == 200

    with app.app_context():
        m_db = Match.query.get(match_id)
        assert dual_write.get_match_player_ids(m_db, WinnerSide.TEAM1) == ["p1", "p2"]
        assert dual_write.get_match_player_ids(m_db, WinnerSide.TEAM2) == ["p3"]


@pytest.mark.integration
def test_update_tournament_route_populates_head_ref_allowlist(app, client, tournament, player):
    """``POST /<event>/update-settings`` should populate ``headref_allowlist``."""
    from models import Player, TO

    with app.app_context():
        t = db.session.merge(tournament)
        p = db.session.merge(player)
        db.session.add(TO(user_id=p.id, user_type="player", event=t.url))
        for pid in ("ref_a", "ref_b"):
            db.session.add(Player(id=pid, name=pid, pw_hash="h"))
        db.session.commit()
        tournament_url = t.url
        login_as(client, p)

    resp = client.post(
        f"/_api/{tournament_url}/update-settings",
        data={
            "name": "Updated Name",
            "head_refs_allowed_list": "ref_a, ref_b",
            "end_date": "2026-12-31",
        },
        follow_redirects=False,
    )
    assert resp.status_code < 400, f"unexpected status {resp.status_code}: {resp.data!r}"

    with app.app_context():
        from models import Tournament

        t_db = Tournament.query.get(tournament_url)
        assert set(dual_write.get_head_ref_allowlist_ids(t_db)) == {"ref_a", "ref_b"}
