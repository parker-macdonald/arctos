"""Integration tests for TO-guarded routes (HTTP-level permission checks)."""

import pytest

from models import TO, db
from tests.utils import login_as


@pytest.mark.integration
def test_tournament_manage_requires_to(app, client, tournament, player, test_db):
    """Non-TO players are denied access to the manage page.

    /_api routes are JSON-preferring, so the decorator returns 403 JSON
    rather than an HTML redirect.
    """
    with app.app_context():
        t = db.session.merge(tournament)
        p = db.session.merge(player)
        login_as(client, p)

    resp = client.get(f"/_api/{t.url}/export-schedule", follow_redirects=False)
    assert resp.status_code == 403


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
