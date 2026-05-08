"""Integration tests for team/player registration and deregistration flows."""

from datetime import datetime

import pytest

from app.domain.enums import RegistrationStatus, TeamRegistrationStatus
from models import League, PlayerRegistration, TeamRegistration, db
from tests.utils import login_as, make_registrable_config


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
def test_team_reregister_reuses_cancelled_tournament_row(app, client, tournament, team):
    """Re-registering after cancellation updates the existing tournament row."""
    with app.app_context():
        t = db.session.merge(tournament)
        tm = db.session.merge(team)
        tournament_url = t.url
        team_id = tm.id
        login_as(client, tm)

    resp1 = client.post(
        f"/_api/{tournament_url}/register-team",
        data={"pseudonym": "First Name"},
    )
    assert resp1.status_code == 200

    with app.app_context():
        reg1 = TeamRegistration.query.filter_by(event=tournament_url, team=team_id).one()
        first_id = reg1.id
        original_registered_at = reg1.registered_at
        reg1.registered_at = datetime(2020, 1, 1)
        db.session.commit()

    resp2 = client.post(f"/_api/{tournament_url}/deregister-team")
    assert resp2.status_code == 200

    resp3 = client.post(
        f"/_api/{tournament_url}/register-team",
        data={"pseudonym": "Second Name"},
    )
    assert resp3.status_code == 200, resp3.get_data(as_text=True)

    with app.app_context():
        regs = TeamRegistration.query.filter_by(event=tournament_url, team=team_id).all()
        assert len(regs) == 1
        reg = regs[0]
        assert reg.id == first_id
        assert reg.status == TeamRegistrationStatus.CONFIRMED
        assert reg.pseudonym == "Second Name"
        assert reg.registered_at != datetime(2020, 1, 1)
        assert reg.registered_at != original_registered_at


@pytest.mark.integration
def test_team_reregister_reuses_cancelled_league_row(app, client, team):
    """League team re-registration keeps a single row per (league, team)."""
    with app.app_context():
        tm = db.session.merge(team)
        cfg = make_registrable_config(team_registration_open=True)
        league = League(
            url="test-league",
            name="Test League",
            published=True,
            registrable_config_id=cfg.id,
        )
        db.session.add(league)
        db.session.commit()
        login_as(client, tm)

    resp1 = client.post(
        "/_api/leagues/test-league/register-team",
        data={"pseudonym": "League First"},
    )
    assert resp1.status_code == 200, resp1.get_data(as_text=True)

    with app.app_context():
        reg1 = TeamRegistration.query.filter_by(league_id="test-league", team=team.id).one()
        first_id = reg1.id
        original_registered_at = reg1.registered_at
        reg1.registered_at = datetime(2020, 1, 1)
        db.session.commit()

    resp2 = client.post("/_api/leagues/test-league/deregister-team")
    assert resp2.status_code == 200, resp2.get_data(as_text=True)

    resp3 = client.post(
        "/_api/leagues/test-league/register-team",
        data={"pseudonym": "League Second"},
    )
    assert resp3.status_code == 200, resp3.get_data(as_text=True)

    with app.app_context():
        regs = TeamRegistration.query.filter_by(league_id="test-league", team=team.id).all()
        assert len(regs) == 1
        reg = regs[0]
        assert reg.id == first_id
        assert reg.status == TeamRegistrationStatus.CONFIRMED
        assert reg.pseudonym == "League Second"
        assert reg.registered_at != datetime(2020, 1, 1)
        assert reg.registered_at != original_registered_at


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
