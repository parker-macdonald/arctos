"""Unit tests for app.services._common helpers."""

import pytest

from app.error_values import Err, Ok
from app.exceptions import ArctosError


@pytest.mark.unit
def test_get_tournament_or_err_returns_ok_when_found(app, test_db, tournament):
    from app.services._common import get_tournament_or_err

    res = get_tournament_or_err(tournament.url)
    assert isinstance(res, Ok)
    assert res.val.url == tournament.url


@pytest.mark.unit
def test_get_tournament_or_err_returns_err_when_missing(app, test_db):
    from app.services._common import get_tournament_or_err

    res = get_tournament_or_err("does-not-exist")
    assert isinstance(res, Err)
    assert isinstance(res.val, ArctosError)
    assert res.val.status_code == 404
    assert res.val.public is True


@pytest.mark.unit
def test_resolve_actor_returns_player(app, test_db, player):
    from app.services._common import resolve_actor

    result = resolve_actor(player.id, "player")
    assert result is not None
    assert result.id == player.id


@pytest.mark.unit
def test_resolve_actor_returns_team(app, test_db, team):
    from app.services._common import resolve_actor

    result = resolve_actor(team.id, "team")
    assert result is not None
    assert result.id == team.id


@pytest.mark.unit
def test_resolve_actor_returns_none_for_unknown_type(app, test_db):
    from app.services._common import resolve_actor

    assert resolve_actor("any-id", "unknown") is None


@pytest.mark.unit
def test_resolve_actor_returns_none_for_missing_id(app, test_db):
    from app.services._common import resolve_actor

    assert resolve_actor("nonexistent-id-xyz", "player") is None


@pytest.mark.unit
def test_current_user_type_for_player(app, test_db, player):
    from app.services._common import current_user_type
    from flask_login import login_user

    with app.test_request_context("/"):
        login_user(player)
        assert current_user_type() == "player"


@pytest.mark.unit
def test_current_user_type_for_team(app, test_db, team):
    from app.services._common import current_user_type
    from flask_login import login_user

    with app.test_request_context("/"):
        login_user(team)
        assert current_user_type() == "team"


@pytest.mark.unit
def test_scope_event_factory():
    from app.services._common import Scope

    s = Scope.event("test-tourn")
    assert s.is_event is True
    assert s.is_league is False
    assert s.event_url == "test-tourn"
    assert s.league_url is None
    assert s.url == "test-tourn"


@pytest.mark.unit
def test_scope_league_factory():
    from app.services._common import Scope

    s = Scope.league("test-league")
    assert s.is_league is True
    assert s.is_event is False
    assert s.league_url == "test-league"
    assert s.event_url is None
    assert s.url == "test-league"


@pytest.mark.unit
def test_scope_rejects_both_unset():
    from app.services._common import Scope

    with pytest.raises(ValueError):
        Scope()


@pytest.mark.unit
def test_scope_rejects_both_set():
    from app.services._common import Scope

    with pytest.raises(ValueError):
        Scope(event_url="a", league_url="b")


@pytest.mark.unit
def test_scope_is_frozen():
    from app.services._common import Scope
    import dataclasses

    s = Scope.event("test")
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.event_url = "other"
