"""Integration tests for team/player registration and deregistration flows."""

import pytest

from app.domain.enums import RegistrationStatus, TeamRegistrationStatus
from models import PlayerRegistration, TeamRegistration, db
from tests.utils import login_as
from datetime import datetime


@pytest.mark.integration
def test_team_register_and_deregister_flow(app, client, tournament, team):
    """A team can register with a pseudonym and then deregister via the API."""
    with app.app_context():
        t = db.session.merge(tournament)
        tm = db.session.merge(team)
        tournament_url = t.url
        team_id = tm.id
        login_as(client, tm)

    resp = client.post(
        f"/_api/{tournament_url}/register-team",
        data={"pseudonym": "Team Pseudonym"},
    )
    assert resp.status_code == 200

    with app.app_context():
        reg = TeamRegistration.query.filter_by(event=tournament_url, team=team_id).first()
        assert reg is not None
        assert reg.status == TeamRegistrationStatus.CONFIRMED
        assert reg.pseudonym == "Team Pseudonym"

    resp2 = client.post(f"/_api/{tournament_url}/deregister-team")
    assert resp2.status_code == 200

    with app.app_context():
        reg2 = TeamRegistration.query.filter_by(event=tournament_url, team=team_id).first()
        assert reg2 is not None
        assert reg2.status == TeamRegistrationStatus.CANCELLED


@pytest.mark.integration
def test_player_register_and_deregister_flow(app, client, tournament, player):
    with app.app_context():
        t = db.session.merge(tournament)
        p = db.session.merge(player)
        tournament_url = t.url
        player_id = p.id
        login_as(client, p)

    resp = client.post(
        f"/_api/{tournament_url}/register-player",
        data={"jersey_name": "Alice", "jersey_number": "7"},
    )
    assert resp.status_code == 200

    with app.app_context():
        reg = PlayerRegistration.query.filter_by(event=tournament_url, player=player_id).first()
        assert reg is not None
        assert reg.status == "CONFIRMED"
        assert reg.jersey_name == "Alice"
        assert reg.jersey_number == "7"
        assert reg.paid is True
        assert (reg.paid_at is None) or isinstance(reg.paid_at, datetime)

    # Registering again while already CONFIRMED should return 400 (already registered).
    resp_dup = client.post(
        f"/_api/{tournament_url}/register-player",
        data={"jersey_name": "Alice2", "jersey_number": "8"},
    )
    assert resp_dup.status_code == 400
    with app.app_context():
        # Still only one row
        regs = PlayerRegistration.query.filter_by(event=tournament_url, player=player_id).all()
        assert len(regs) == 1

    resp2 = client.post(f"/_api/{tournament_url}/deregister-player")
    assert resp2.status_code == 200

    with app.app_context():
        reg2 = PlayerRegistration.query.filter_by(event=tournament_url, player=player_id).first()
        assert reg2 is not None
        assert reg2.status == RegistrationStatus.CANCELLED
