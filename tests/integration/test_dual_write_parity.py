"""End-to-end parity tests that exercise real HTTP routes and verify the
dual-write keeps the new normalised tables in lockstep with the legacy blobs.

Per blob/normalised-table pair, this module picks one route that genuinely
writes the legacy column at runtime, drives it through the test client,
then runs the corresponding ``assert_*_parity`` helper to confirm the new
table caught up.

These tests are integration-marked because they go through the full
Flask request/response stack and hit the database, not just the model
layer.
"""

from __future__ import annotations

import json

import pytest

from app.domain.enums import MatchStatus
from app.services import dual_write
from models import Match, db
from tests.utils import login_as


@pytest.mark.integration
def test_start_match_route_keeps_match_players_in_parity(app, client, tournament, head_ref_player, seeded_teams):
    """``POST /_api/<event>/start-match`` writes ``team1_players`` / ``team2_players``;
    the dual-write must populate ``match_players`` so parity holds afterwards."""
    with app.app_context():
        t = db.session.merge(tournament)
        ref = db.session.merge(head_ref_player)
        # Players named on the roster have to actually exist for the
        # dual-write FK check to mirror them. Add three.
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
        # Sanity: the legacy column was written as expected.
        assert json.loads(m_db.team1_players) == ["p1", "p2"]
        assert json.loads(m_db.team2_players) == ["p3"]
        # And the new table is in lockstep.
        dual_write.assert_match_players_parity(m_db)


@pytest.mark.integration
def test_update_tournament_route_keeps_head_ref_allowlist_in_parity(app, client, tournament, player):
    """``POST /<event>/update-tournament`` writes ``head_refs_allowed_list``;
    the dual-write must reconcile ``headref_allowlist`` so parity holds."""
    from models import Player, TO

    with app.app_context():
        t = db.session.merge(tournament)
        p = db.session.merge(player)
        # The acting user must be a TO to hit the route.
        db.session.add(TO(user_id=p.id, user_type="player", event=t.url))
        # Two real players the new CSV value will reference.
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
            # The route requires end_date; everything else uses .get() defaults.
            "end_date": "2026-12-31",
        },
        follow_redirects=False,
    )
    # The route either redirects on success or returns 200; both indicate
    # the write went through (the 4xx/5xx is what we'd reject).
    assert resp.status_code < 400, f"unexpected status {resp.status_code}: {resp.data!r}"

    with app.app_context():
        from models import Tournament

        t_db = Tournament.query.get(tournament_url)
        assert t_db.head_refs_allowed_list == "ref_a, ref_b"
        dual_write.assert_head_ref_allowlist_parity(t_db)
