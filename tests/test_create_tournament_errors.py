"""Reproduction tests for create-tournament errors documented in Ideas.md."""

import pytest

from models import League, RegistrableConfig, TO, Tournament, db
from tests.utils import login_as, make_registrable_config


@pytest.fixture
def player_user(test_db):
    from models import Player

    p = Player(id="coolcatmona", name="Mona", pw_hash="x", phone="1")
    p.set_password("pw")
    db.session.add(p)
    db.session.commit()
    db.session.refresh(p)
    return p


@pytest.mark.integration
def test_create_standalone_tournament(client, player_user):
    """Standalone tournament creation should succeed (Error #1 reproduction)."""
    login_as(client, player_user)
    resp = client.post(
        "/_api/create-tournament",
        data={"name": "Standalone", "url": "ha-standalone"},
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert Tournament.query.get("ha-standalone") is not None
    rc = RegistrableConfig.query.filter_by(id=Tournament.query.get("ha-standalone").registrable_config_id).one()
    assert rc.team_registration_open is False
    assert rc.player_registration_open is False


@pytest.mark.integration
def test_create_event_for_league(client, player_user):
    """Tournament attached to a league should commit cleanly (Error #2 reproduction)."""
    rc = make_registrable_config()
    league = League(url="lg", name="Test League", registrable_config_id=rc.id)
    db.session.add(league)
    db.session.flush()
    db.session.add(TO(user_id=player_user.id, user_type="player", event=None, league_id="lg"))
    db.session.commit()

    login_as(client, player_user)
    resp = client.post(
        "/_api/create-tournament",
        data={"name": "League Event", "url": "ha", "league_id": "lg"},
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    t = Tournament.query.get("ha")
    assert t is not None
    assert t.league_id == "lg"


@pytest.mark.integration
def test_create_standalone_tournament_rejects_invalid_url_slug(client, player_user):
    login_as(client, player_user)
    resp = client.post(
        "/_api/create-tournament",
        data={"name": "Standalone", "url": "/bad-slug"},
    )
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["success"] is False
    assert "letters, numbers, or -_~." in body["error"]
    assert Tournament.query.get("/bad-slug") is None
    assert Tournament.query.get("bad-slug") is None


@pytest.mark.integration
def test_create_tournament_rejects_empty_cleaned_url_slug(client, player_user):
    login_as(client, player_user)
    resp = client.post(
        "/_api/create-tournament",
        data={"name": "Standalone", "url": " !!! "},
    )
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["success"] is False
    assert "letters, numbers, or -_~." in body["error"]


@pytest.mark.integration
def test_create_league_rejects_invalid_url_slug(client, player_user):
    login_as(client, player_user)
    resp = client.post(
        "/_api/create-league",
        data={"league_name": "League", "league_url": "/league-slug"},
    )
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["success"] is False
    assert "letters, numbers, or -_~." in body["error"]
    assert League.query.get("/league-slug") is None
    assert League.query.get("league-slug") is None
