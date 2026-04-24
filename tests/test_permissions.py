"""Tests for PermissionService and TO-guarded routes."""

import pytest

from app.services.permission_service import PermissionService
from models import TO, Tournament, db
from datetime import datetime, timezone
from tests.utils import login_as, make_registrable_config


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
        db.session.add(TO(user_id=p.id, user_type="player", event=t.url))
        db.session.commit()

        assert PermissionService.can_view_tournament("private-tournament", p) is True


@pytest.mark.integration
def test_tournament_manage_requires_to(app, client, tournament, player, test_db):
    """Non-TO players are redirected away from the manage page."""
    # Not a TO -> redirect
    with app.app_context():
        t = db.session.merge(tournament)
        p = db.session.merge(player)
        login_as(client, p)

    resp = client.get(f"/_api/{t.url}/export-schedule", follow_redirects=False)
    assert resp.status_code in (301, 302, 303, 307, 308)


@pytest.mark.integration
def test_tournament_manage_allows_to(app, client, tournament, player, test_db):
    """Tournament Organisers can access the manage page (HTTP 200)."""
    with app.app_context():
        t = db.session.merge(tournament)
        p = db.session.merge(player)
        db.session.add(TO(user_id=p.id, user_type="player", event=t.url))
        db.session.commit()
        login_as(client, p)
        tournament_url = t.url

    resp = client.get(f"/_api/{tournament_url}/export-schedule")
    assert resp.status_code == 200
