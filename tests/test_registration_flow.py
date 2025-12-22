import pytest

from models import PlayerRegistration, TeamRegistration, db
from tests.utils import login_as
from datetime import datetime


@pytest.mark.integration
def test_team_register_and_deregister_flow(app, client, tournament, team):
    with app.app_context():
        t = db.session.merge(tournament)
        tm = db.session.merge(team)
        tournament_url = t.url
        team_id = tm.id
        login_as(client, tm)

    resp = client.post(
        f"/{tournament_url}/register-team",
        data={"pseudonym": "Team Pseudonym"},
        follow_redirects=False,
    )
    assert resp.status_code in (301, 302, 303, 307, 308)

    reg = TeamRegistration.query.filter_by(event=tournament_url, team=team_id).first()
    assert reg is not None
    assert reg.status == "CONFIRMED"
    assert reg.pseudonym == "Team Pseudonym"

    resp2 = client.post(f"/{tournament_url}/deregister-team", follow_redirects=False)
    assert resp2.status_code in (301, 302, 303, 307, 308)

    reg2 = TeamRegistration.query.filter_by(event=tournament_url, team=team_id).first()
    assert reg2 is not None
    assert reg2.status == "CANCELLED"


@pytest.mark.integration
def test_player_register_and_deregister_flow(app, client, tournament, player):
    with app.app_context():
        t = db.session.merge(tournament)
        p = db.session.merge(player)
        tournament_url = t.url
        player_id = p.id
        login_as(client, p)

    resp = client.post(
        f"/{tournament_url}/register-player",
        data={"jersey_name": "Alice", "jersey_number": "7"},
        follow_redirects=False,
    )
    assert resp.status_code in (301, 302, 303, 307, 308)

    reg = PlayerRegistration.query.filter_by(event=tournament_url, player=player_id).first()
    assert reg is not None
    assert reg.status == "CONFIRMED"
    assert reg.jersey_name == "Alice"
    assert reg.jersey_number == "7"
    assert reg.paid is True
    assert (reg.paid_at is None) or isinstance(reg.paid_at, datetime)

    # Registering again should NOT create a second registration row.
    resp_dup = client.post(
        f"/{tournament_url}/register-player",
        data={"jersey_name": "Alice2", "jersey_number": "8"},
        follow_redirects=False,
    )
    assert resp_dup.status_code in (301, 302, 303, 307, 308)
    regs = PlayerRegistration.query.filter_by(event=tournament_url, player=player_id).all()
    assert len(regs) == 1

    resp2 = client.post(f"/{tournament_url}/deregister-player", follow_redirects=False)
    assert resp2.status_code in (301, 302, 303, 307, 308)

    reg2 = PlayerRegistration.query.filter_by(event=tournament_url, player=player_id).first()
    assert reg2 is not None
    assert reg2.status == "CANCELLED"


