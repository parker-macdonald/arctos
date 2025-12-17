import json

import pytest

from models import Match, db
from tests.utils import login_as


@pytest.mark.integration
def test_start_match_post_starts_match(client, tournament, head_ref_player):
    from tests.conftest import app

    with app.app_context():
        t = db.session.merge(tournament)
        ref = db.session.merge(head_ref_player)
        tournament_url = t.url
        ref_id = ref.id
        login_as(client, ref)

        m = Match(
            name="Start Me",
            event=tournament_url,
            schedule_type="DYNAMIC",
            set_type="SETS",
            status="NOT_STARTED",
            nominal_length=60,
            field="Field 1",
        )
        db.session.add(m)
        db.session.commit()
        match_id = m.uuid

    resp = client.post(
        f"/{tournament_url}/start-match",
        data={
            "match_id": match_id,
            "team1_players": "p1,p2",
            "team2_players": "p3",
            "match_notes": "hello",
        },
        follow_redirects=False,
    )
    assert resp.status_code in (301, 302, 303, 307, 308)

    m2 = Match.query.get(match_id)
    assert m2.status == "IN_PROGRESS"
    assert m2.started_by == ref_id
    assert json.loads(m2.team1_players) == ["p1", "p2"]
    assert json.loads(m2.team2_players) == ["p3"]


@pytest.mark.integration
def test_start_match_post_rejects_overlap(client, tournament, head_ref_player):
    from tests.conftest import app

    with app.app_context():
        t = db.session.merge(tournament)
        ref = db.session.merge(head_ref_player)
        tournament_url = t.url
        login_as(client, ref)

        m = Match(
            name="Overlap",
            event=tournament_url,
            schedule_type="DYNAMIC",
            set_type="SETS",
            status="NOT_STARTED",
            nominal_length=60,
            field="Field 1",
        )
        db.session.add(m)
        db.session.commit()
        match_id = m.uuid

    resp = client.post(
        f"/{tournament_url}/start-match",
        data={
            "match_id": match_id,
            "team1_players": "p1,p2",
            "team2_players": "p2,p3",
        },
        follow_redirects=False,
    )
    assert resp.status_code in (301, 302, 303, 307, 308)

    m2 = Match.query.get(match_id)
    assert m2.status == "NOT_STARTED"


