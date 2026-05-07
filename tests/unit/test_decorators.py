"""Unit tests for app.utils.decorators helpers."""

import pytest


# ---------------------------------------------------------------------------
# wants_json helper tests  (use the session-scoped ``app`` - no HTTP requests)
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_wants_json_for_json_content_type(app):
    from app.utils.decorators import wants_json

    with app.test_request_context("/foo", json={"a": 1}):
        from flask import request
        assert wants_json(request) is True


@pytest.mark.unit
def test_wants_json_for_api_path(app):
    from app.utils.decorators import wants_json

    with app.test_request_context("/_api/something"):
        from flask import request
        assert wants_json(request) is True


@pytest.mark.unit
def test_wants_json_for_accept_header(app):
    from app.utils.decorators import wants_json

    with app.test_request_context("/foo", headers={"Accept": "application/json"}):
        from flask import request
        assert wants_json(request) is True


@pytest.mark.unit
def test_wants_json_false_for_html_request(app):
    from app.utils.decorators import wants_json

    with app.test_request_context("/foo", headers={"Accept": "text/html"}):
        from flask import request
        assert wants_json(request) is False


@pytest.mark.unit
def test_wants_json_false_for_no_accept_header(app):
    """When no Accept header is set (typical browser default), the helper
    should NOT default to JSON. Default browser Accept is broadly permissive
    so HTML wins."""
    from app.utils.decorators import wants_json

    with app.test_request_context("/foo"):
        from flask import request
        assert wants_json(request) is False


# ---------------------------------------------------------------------------
# require_tournament_organizer tests
#
# These register routes dynamically, so they use ``fresh_app`` (function-
# scoped) from tests/unit/conftest.py rather than the shared session-scoped
# ``app``.  This avoids Flask's "no new routes after first request" guard
# when running under pytest-xdist.
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_require_tournament_organizer_html_redirects_when_not_to(fresh_app):
    """HTML requests get flash + redirect when the user is not a TO."""
    from app.utils.decorators import require_tournament_organizer
    from models import Tournament, Player, db
    from tests.utils import make_registrable_config
    from datetime import datetime, timedelta, timezone

    with fresh_app.app_context():
        cfg = make_registrable_config(
            team_registration_open=True,
            player_registration_open=True,
            n_max_teams=8,
            max_team_size_roster=10,
            max_team_size_field=7,
        )
        tourn = Tournament(
            url="dec-test-html",
            name="Dec Test HTML",
            start_date=datetime.now(timezone.utc),
            end_date=datetime.now(timezone.utc) + timedelta(days=1),
            location="Test",
            max_field_size=14,
            published=True,
            schedule_published=True,
            registrable_config_id=cfg.id,
        )
        db.session.add(tourn)
        p = Player(id="dec_html_player", name="HTML Player", pw_hash="x", phone="0000000000")
        p.set_password("pass")
        db.session.add(p)
        db.session.commit()
        db.session.refresh(p)

    @fresh_app.route("/_test_html_to/<tournament_url>")
    @require_tournament_organizer()
    def _test_html_to(tournament_url):
        return f"OK for {tournament_url}"

    with fresh_app.app_context():
        player = db.session.get(Player, "dec_html_player")

    with fresh_app.test_client(user=player) as logged:
        resp = logged.get(
            "/_test_html_to/dec-test-html",
            headers={"Accept": "text/html"},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)


@pytest.mark.unit
def test_require_tournament_organizer_json_returns_403_when_not_to(fresh_app):
    """JSON requests get a 403 json_error response."""
    from app.utils.decorators import require_tournament_organizer
    from models import Tournament, Player, db
    from tests.utils import make_registrable_config
    from datetime import datetime, timedelta, timezone

    with fresh_app.app_context():
        cfg = make_registrable_config(
            team_registration_open=True,
            player_registration_open=True,
            n_max_teams=8,
            max_team_size_roster=10,
            max_team_size_field=7,
        )
        tourn = Tournament(
            url="dec-test-json",
            name="Dec Test JSON",
            start_date=datetime.now(timezone.utc),
            end_date=datetime.now(timezone.utc) + timedelta(days=1),
            location="Test",
            max_field_size=14,
            published=True,
            schedule_published=True,
            registrable_config_id=cfg.id,
        )
        db.session.add(tourn)
        p = Player(id="dec_json_player", name="JSON Player", pw_hash="x", phone="1111111111")
        p.set_password("pass")
        db.session.add(p)
        db.session.commit()
        db.session.refresh(p)

    @fresh_app.route("/_test_json_to/<tournament_url>")
    @require_tournament_organizer()
    def _test_json_to(tournament_url):
        return {"ok": True}

    with fresh_app.app_context():
        player = db.session.get(Player, "dec_json_player")

    with fresh_app.test_client(user=player) as logged:
        resp = logged.get(
            "/_test_json_to/dec-test-json",
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 403
        body = resp.get_json()
        assert body["success"] is False
        assert "error" in body


@pytest.mark.unit
def test_require_tournament_organizer_grants_access_when_to_exists(fresh_app):
    """User with a TO row is granted access."""
    from app.utils.decorators import require_tournament_organizer
    from models import TO, Tournament, Player, db
    from tests.utils import make_registrable_config
    from datetime import datetime, timedelta, timezone

    with fresh_app.app_context():
        cfg = make_registrable_config(
            team_registration_open=True,
            player_registration_open=True,
            n_max_teams=8,
            max_team_size_roster=10,
            max_team_size_field=7,
        )
        tourn = Tournament(
            url="dec-test-grant",
            name="Dec Test Grant",
            start_date=datetime.now(timezone.utc),
            end_date=datetime.now(timezone.utc) + timedelta(days=1),
            location="Test",
            max_field_size=14,
            published=True,
            schedule_published=True,
            registrable_config_id=cfg.id,
        )
        db.session.add(tourn)
        p = Player(id="dec_grant_player", name="Grant Player", pw_hash="x", phone="2222222222")
        p.set_password("pass")
        db.session.add(p)
        db.session.flush()
        db.session.add(TO(user_id=p.id, user_type="player", event=tourn.url))
        db.session.commit()
        db.session.refresh(p)

    @fresh_app.route("/_test_to_grant/<tournament_url>")
    @require_tournament_organizer()
    def _test_to_grant(tournament_url):
        return {"ok": True}

    with fresh_app.app_context():
        player = db.session.get(Player, "dec_grant_player")

    with fresh_app.test_client(user=player) as logged:
        resp = logged.get(
            "/_test_to_grant/dec-test-grant",
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# require_league_organizer tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_require_league_organizer_grants_access(fresh_app):
    """User with a TO row for a league is granted access."""
    from app.utils.decorators import require_league_organizer
    from models import TO, League, Player, db
    from tests.utils import make_registrable_config

    with fresh_app.app_context():
        cfg = make_registrable_config()
        league = League(
            url="dec-test-league-grant",
            name="Dec League Grant",
            registrable_config_id=cfg.id,
        )
        db.session.add(league)
        p = Player(id="dec_lg_grant_player", name="LG Grant Player", pw_hash="x", phone="3333333333")
        p.set_password("pass")
        db.session.add(p)
        db.session.flush()
        db.session.add(TO(user_id=p.id, user_type="player", league_id=league.url))
        db.session.commit()
        db.session.refresh(p)

    @fresh_app.route("/_test_lg_grant/<league_url>", endpoint="_test_lg_grant")
    @require_league_organizer()
    def _test_lg_grant(league_url):
        return {"ok": True}

    with fresh_app.app_context():
        player = db.session.get(Player, "dec_lg_grant_player")

    with fresh_app.test_client(user=player) as logged:
        resp = logged.get(
            "/_test_lg_grant/dec-test-league-grant",
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 200


@pytest.mark.unit
def test_require_league_organizer_denies_with_403_json(fresh_app):
    """JSON requests get a 403 json_error response when user is not a LO."""
    from app.utils.decorators import require_league_organizer
    from models import League, Player, db
    from tests.utils import make_registrable_config

    with fresh_app.app_context():
        cfg = make_registrable_config()
        league = League(
            url="dec-test-league-deny",
            name="Dec League Deny",
            registrable_config_id=cfg.id,
        )
        db.session.add(league)
        p = Player(id="dec_lg_deny_player", name="LG Deny Player", pw_hash="x", phone="4444444444")
        p.set_password("pass")
        db.session.add(p)
        db.session.commit()
        db.session.refresh(p)

    @fresh_app.route("/_test_lg_deny/<league_url>", endpoint="_test_lg_deny")
    @require_league_organizer()
    def _test_lg_deny(league_url):
        return {"ok": True}

    with fresh_app.app_context():
        player = db.session.get(Player, "dec_lg_deny_player")

    with fresh_app.test_client(user=player) as logged:
        resp = logged.get(
            "/_test_lg_deny/dec-test-league-deny",
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 403
        body = resp.get_json()
        assert body["success"] is False
        assert "error" in body


@pytest.mark.unit
def test_require_league_organizer_html_redirects_when_not_lo(fresh_app):
    """HTML requests get flash + redirect when the user is not a LO."""
    from app.utils.decorators import require_league_organizer
    from models import League, Player, db
    from tests.utils import make_registrable_config

    with fresh_app.app_context():
        cfg = make_registrable_config()
        league = League(
            url="dec-test-league-html",
            name="Dec League HTML",
            registrable_config_id=cfg.id,
        )
        db.session.add(league)
        p = Player(id="dec_lg_html_player", name="LG HTML Player", pw_hash="x", phone="5555555555")
        p.set_password("pass")
        db.session.add(p)
        db.session.commit()
        db.session.refresh(p)

    @fresh_app.route("/_test_lg_html/<league_url>", endpoint="_test_lg_html")
    @require_league_organizer()
    def _test_lg_html(league_url):
        return f"OK for {league_url}"

    with fresh_app.app_context():
        player = db.session.get(Player, "dec_lg_html_player")

    with fresh_app.test_client(user=player) as logged:
        resp = logged.get(
            "/_test_lg_html/dec-test-league-html",
            headers={"Accept": "text/html"},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)


@pytest.mark.unit
def test_require_json_body_415_for_non_json(fresh_app):
    from app.utils.decorators import require_json_body

    @fresh_app.route("/_test_json_body_415", methods=["POST"], endpoint="_test_json_body_415")
    @require_json_body()
    def _test_json_body_415():
        return {"ok": True}

    with fresh_app.test_client() as c:
        resp = c.post("/_test_json_body_415", data="not-json", content_type="text/plain")
        assert resp.status_code == 415
        body = resp.get_json()
        assert body["success"] is False
        assert "error" in body


@pytest.mark.unit
def test_require_json_body_stashes_parsed_body_on_g(fresh_app):
    from flask import g
    from app.utils.decorators import require_json_body

    captured = {}

    @fresh_app.route("/_test_json_body_ok", methods=["POST"], endpoint="_test_json_body_ok")
    @require_json_body()
    def _test_json_body_ok():
        captured["body"] = g.json_body
        return {"ok": True}

    with fresh_app.test_client() as c:
        resp = c.post("/_test_json_body_ok", json={"foo": 42, "bar": "baz"})
        assert resp.status_code == 200
        assert captured["body"] == {"foo": 42, "bar": "baz"}


@pytest.mark.unit
def test_require_json_body_empty_body_defaults_to_empty_dict(fresh_app):
    from flask import g
    from app.utils.decorators import require_json_body

    captured = {}

    @fresh_app.route("/_test_json_body_empty", methods=["POST"], endpoint="_test_json_body_empty")
    @require_json_body()
    def _test_json_body_empty():
        captured["body"] = g.json_body
        return {"ok": True}

    with fresh_app.test_client() as c:
        # Empty JSON body
        resp = c.post("/_test_json_body_empty", data="", content_type="application/json")
        assert resp.status_code == 200
        assert captured["body"] == {}
