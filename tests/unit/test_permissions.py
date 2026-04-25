"""Unit tests for PermissionService (no HTTP, no test client)."""

from datetime import datetime, timezone

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
