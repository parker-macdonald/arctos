"""Unit tests for PermissionService (no HTTP, no test client)."""

from datetime import datetime, timedelta, timezone

import pytest

from app.services.permission_service import PermissionService
from models import TO, Tournament, db
from tests.utils import make_registrable_config


@pytest.mark.unit
def test_permission_service_is_tournament_organizer_false_when_missing_to(app, test_db, tournament, player):
    """is_tournament_organizer returns False when no TO row exists for the player."""
    with app.app_context():
        t = db.session.merge(tournament)
        p = db.session.merge(player)
        # ensure there is no TO entry
        TO.query.filter_by(event=t.url, user_id=p.id, user_type="player").delete()
        db.session.commit()
        assert PermissionService.is_tournament_organizer(t.url, p) is False


@pytest.mark.unit
def test_permission_service_is_tournament_organizer_true_when_to_exists(app, test_db, tournament, player):
    """is_tournament_organizer returns True when a matching TO row is present."""
    with app.app_context():
        t = db.session.merge(tournament)
        p = db.session.merge(player)
        db.session.add(TO(user_id=p.id, user_type="player", event=t.url))
        db.session.commit()
        assert PermissionService.is_tournament_organizer(t.url, p) is True


@pytest.mark.unit
def test_permission_service_can_view_unpublished_tournament_for_to(app, test_db, player):
    """can_view_tournament returns True for an unpublished tournament when the user is its TO."""
    with app.app_context():
        p = db.session.merge(player)
        cfg = make_registrable_config()
        t = Tournament(
            url="private-tournament",
            name="Private Tournament",
            start_date=datetime.now(timezone.utc),
            published=False,
            registrable_config_id=cfg.id,
        )
        db.session.add(t)
        # Flush so the Tournament row is INSERTed before the TO row that
        # references it. SQLAlchemy's unit of work only orders inserts via
        # ``relationship()`` declarations; bare ``ForeignKey`` columns (which
        # is what ``TO.event`` is) don't establish a dependency, so without
        # this flush the TO insert can fire first and trip the FK pragma
        # enabled in ``app.set_sqlite_pragmas``.
        db.session.flush()
        db.session.add(TO(user_id=p.id, user_type="player", event=t.url))
        db.session.commit()

        assert PermissionService.can_view_tournament("private-tournament", p) is True


@pytest.mark.unit
def test_user_type_returns_userdata_player(app, test_db, player):
    """user_type returns Some(UserType.PLAYER) for a player user."""
    from app.error_values import Some
    from app.domain.enums import UserType

    with app.app_context():
        p = db.session.merge(player)
        result = PermissionService.user_type(p)
        assert isinstance(result, Some)
        assert isinstance(result.val, UserType)  # Strict type check forces the migration
        assert result.val == UserType.PLAYER
        assert result.val == "player"


@pytest.mark.unit
def test_user_type_returns_userdata_team(app, test_db, team):
    """user_type returns Some(UserType.TEAM) for a team user."""
    from app.error_values import Some
    from app.domain.enums import UserType

    with app.app_context():
        t = db.session.merge(team)
        result = PermissionService.user_type(t)
        assert isinstance(result, Some)
        assert isinstance(result.val, UserType)
        assert result.val == UserType.TEAM


@pytest.mark.unit
def test_user_type_returns_null_for_none():
    """user_type returns Null for None."""
    from app.error_values import Null

    result = PermissionService.user_type(None)
    assert isinstance(result, Null)


@pytest.mark.unit
def test_is_tournament_organizer_grants_via_league_id(app, test_db, player):
    """A league-season TO is granted access to event-only routes on
    tournaments under that league."""
    from app.models.league import League

    with app.app_context():
        p = db.session.merge(player)

        league = League(
            url="league-tourn-test-1",
            name="League Tourn Test 1",
            registrable_config_id=make_registrable_config().id,
        )
        db.session.add(league)
        db.session.commit()

        t = Tournament(
            url="league-tourn-test-1-evt",
            name="League Tourn Test 1 Evt",
            start_date=datetime.now(timezone.utc),
            end_date=datetime.now(timezone.utc) + timedelta(days=1),
            location="L1",
            max_field_size=14,
            published=True,
            league_id=league.url,
        )
        db.session.add(t)
        db.session.flush()
        db.session.add(TO(user_id=p.id, user_type="player", league_id=league.url))
        db.session.commit()

        assert PermissionService.is_tournament_organizer(t.url, p) is True


@pytest.mark.unit
def test_is_tournament_organizer_denies_when_no_event_or_league_to(
    app, test_db, tournament, player
):
    """is_tournament_organizer returns False when no matching TO exists."""
    with app.app_context():
        t = db.session.merge(tournament)
        p = db.session.merge(player)
        # ensure there is no TO entry
        TO.query.filter_by(event=t.url, user_id=p.id, user_type="player").delete()
        db.session.commit()
        assert PermissionService.is_tournament_organizer(t.url, p) is False


@pytest.mark.unit
def test_is_tournament_organizer_returns_false_when_tournament_missing(app, test_db, player):
    """is_tournament_organizer returns False when tournament does not exist."""
    with app.app_context():
        p = db.session.merge(player)
        assert PermissionService.is_tournament_organizer("does-not-exist-xyz", p) is False


@pytest.mark.unit
def test_is_league_organizer_true_when_to_exists(app, test_db, player):
    from app.models.league import League

    with app.app_context():
        p = db.session.merge(player)
        league = League(
            url="league-org-test-1",
            name="League Org Test 1",
            registrable_config_id=make_registrable_config().id,
        )
        db.session.add(league)
        db.session.add(TO(user_id=p.id, user_type="player", league_id=league.url))
        db.session.commit()

        assert PermissionService.is_league_organizer(league.url, p) is True


@pytest.mark.unit
def test_is_league_organizer_false_when_no_to(app, test_db, player):
    from app.models.league import League

    with app.app_context():
        p = db.session.merge(player)
        league = League(
            url="league-org-test-2",
            name="League Org Test 2",
            registrable_config_id=make_registrable_config().id,
        )
        db.session.add(league)
        db.session.commit()

        assert PermissionService.is_league_organizer(league.url, p) is False


@pytest.mark.unit
def test_is_league_organizer_false_for_none_user(app, test_db):
    with app.app_context():
        assert PermissionService.is_league_organizer("league-x", None) is False
