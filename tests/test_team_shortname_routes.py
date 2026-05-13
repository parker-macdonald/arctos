"""Integration tests for the shortname field on team registration routes."""

from __future__ import annotations

import pytest

from models import TeamRegistration, db
from tests.utils import login_as


@pytest.mark.integration
def test_register_team_for_tournament_persists_shortname(app, client, tournament, team):
    with app.app_context():
        t = db.session.merge(tournament)
        tm = db.session.merge(team)
        tournament_url = t.url
        team_id = tm.id
        login_as(client, tm)

    resp = client.post(
        f"/_api/{tournament_url}/register-team",
        data={"pseudonym": "Pseudo", "shortname": "BCS"},
    )
    assert resp.status_code == 200, resp.data

    with app.app_context():
        reg = TeamRegistration.query.filter_by(event=tournament_url, team=team_id).first()
        assert reg is not None
        assert reg.shortname == "BCS"


@pytest.mark.integration
def test_register_team_for_tournament_omits_shortname_stores_null(app, client, tournament, team):
    with app.app_context():
        t = db.session.merge(tournament)
        tm = db.session.merge(team)
        tournament_url = t.url
        team_id = tm.id
        login_as(client, tm)

    resp = client.post(
        f"/_api/{tournament_url}/register-team",
        data={"pseudonym": "Pseudo"},
    )
    assert resp.status_code == 200

    with app.app_context():
        reg = TeamRegistration.query.filter_by(event=tournament_url, team=team_id).first()
        assert reg.shortname is None


@pytest.mark.integration
def test_register_team_for_tournament_rejects_13_char_shortname(app, client, tournament, team):
    with app.app_context():
        t = db.session.merge(tournament)
        tm = db.session.merge(team)
        tournament_url = t.url
        login_as(client, tm)

    resp = client.post(
        f"/_api/{tournament_url}/register-team",
        data={"pseudonym": "Pseudo", "shortname": "x" * 13},
    )
    assert resp.status_code == 400
    body = resp.get_json() or {}
    haystack = str(body).lower()
    assert "shortname" in haystack
    assert "12" in haystack


@pytest.mark.integration
def test_tournament_match_detail_exposes_team_shortnames(app, client, tournament, team):
    """When a match has registered teams with shortnames, the detail payload exposes them."""
    import uuid as uuid_lib
    from models import Match
    from app.services.registration_service import RegistrationService
    from app.services._common import Scope

    with app.app_context():
        t = db.session.merge(tournament)
        tm = db.session.merge(team)
        tournament_url = t.url
        team_id = tm.id

        # Register the team with a shortname through the service.
        res = RegistrationService.register_team(
            Scope.event(tournament_url),
            team_id,
            pseudonym="Pseudo",
            shortname="BCS",
        )
        assert res.is_ok(), res.unwrap_err()

        # Create a minimal match with that team as team1.
        match = Match(
            uuid=str(uuid_lib.uuid4()),
            name="m1",
            event=tournament_url,
            team1=team_id,
            team1_initial=team_id,
            team2=None,
            team2_initial="TBD",
        )
        db.session.add(match)
        db.session.commit()
        match_uuid = match.uuid

        login_as(client, tm)

    resp = client.get(f"/_api/tournaments/{tournament_url}/match?id={match_uuid}")
    assert resp.status_code == 200, resp.data
    body = resp.get_json()
    match_payload = body.get("match") if isinstance(body, dict) else None
    assert match_payload is not None, body
    assert match_payload.get("team1_shortname") == "BCS"
    assert match_payload.get("team2_shortname") is None


@pytest.mark.integration
def test_put_edit_registration_sets_shortname(app, client, tournament, team):
    """PUT with non-empty shortname sets the column."""
    with app.app_context():
        t = db.session.merge(tournament)
        tm = db.session.merge(team)
        tournament_url = t.url
        team_id = tm.id

        # Pre-register the team so the PUT has a row to update.
        from app.services.registration_service import RegistrationService
        from app.services._common import Scope

        res = RegistrationService.register_team(
            Scope.event(tournament_url),
            team_id,
            pseudonym="Pseudo",
        )
        assert res.is_ok()

        login_as(client, tm)

    resp = client.put(
        f"/_api/tournaments/{tournament_url}/registrations/team/me",
        json={"shortname": "BCS"},
    )
    assert resp.status_code == 200, resp.data

    with app.app_context():
        reg = TeamRegistration.query.filter_by(event=tournament_url, team=team_id).first()
        assert reg.shortname == "BCS"


@pytest.mark.integration
def test_put_edit_registration_clears_shortname_via_empty_string(app, client, tournament, team):
    """PUT with shortname="" clears the column."""
    with app.app_context():
        t = db.session.merge(tournament)
        tm = db.session.merge(team)
        tournament_url = t.url
        team_id = tm.id

        from app.services.registration_service import RegistrationService
        from app.services._common import Scope

        res = RegistrationService.register_team(
            Scope.event(tournament_url),
            team_id,
            pseudonym="Pseudo",
            shortname="BCS",
        )
        assert res.is_ok()

        login_as(client, tm)

    resp = client.put(
        f"/_api/tournaments/{tournament_url}/registrations/team/me",
        json={"shortname": ""},
    )
    assert resp.status_code == 200, resp.data

    with app.app_context():
        reg = TeamRegistration.query.filter_by(event=tournament_url, team=team_id).first()
        assert reg.shortname is None


@pytest.mark.integration
def test_put_edit_registration_clears_shortname_via_null(app, client, tournament, team):
    """PUT with shortname=null clears the column."""
    with app.app_context():
        t = db.session.merge(tournament)
        tm = db.session.merge(team)
        tournament_url = t.url
        team_id = tm.id

        from app.services.registration_service import RegistrationService
        from app.services._common import Scope

        res = RegistrationService.register_team(
            Scope.event(tournament_url),
            team_id,
            pseudonym="Pseudo",
            shortname="BCS",
        )
        assert res.is_ok()

        login_as(client, tm)

    resp = client.put(
        f"/_api/tournaments/{tournament_url}/registrations/team/me",
        json={"shortname": None},
    )
    assert resp.status_code == 200, resp.data

    with app.app_context():
        reg = TeamRegistration.query.filter_by(event=tournament_url, team=team_id).first()
        assert reg.shortname is None


@pytest.mark.integration
def test_put_edit_registration_preserves_shortname_when_key_absent(app, client, tournament, team):
    """PUT without shortname key leaves the column unchanged."""
    with app.app_context():
        t = db.session.merge(tournament)
        tm = db.session.merge(team)
        tournament_url = t.url
        team_id = tm.id

        from app.services.registration_service import RegistrationService
        from app.services._common import Scope

        res = RegistrationService.register_team(
            Scope.event(tournament_url),
            team_id,
            pseudonym="Pseudo",
            shortname="BCS",
        )
        assert res.is_ok()

        login_as(client, tm)

    # PUT body containing ONLY pseudonym - no shortname key at all.
    resp = client.put(
        f"/_api/tournaments/{tournament_url}/registrations/team/me",
        json={"pseudonym": "Pseudo2"},
    )
    assert resp.status_code == 200, resp.data

    with app.app_context():
        reg = TeamRegistration.query.filter_by(event=tournament_url, team=team_id).first()
        assert reg.pseudonym == "Pseudo2"
        assert reg.shortname == "BCS"  # preserved
