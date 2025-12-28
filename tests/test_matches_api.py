import pytest

from models import Match, Point, db
from tests.utils import login_as


@pytest.mark.integration
def test_update_set_missing_fields_returns_400(
    app, client, tournament, head_ref_player
):
    with app.app_context():
        t = db.session.merge(tournament)
        ref = db.session.merge(head_ref_player)
        login_as(client, ref)

    resp = client.post(f"/{t.url}/match-actions/update-set", json={})
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["success"] is False
    assert "Point ID" in data["error"]


@pytest.mark.integration
def test_get_points_requires_match_id(app, client, tournament, head_ref_player):
    with app.app_context():
        t = db.session.merge(tournament)
        ref = db.session.merge(head_ref_player)
        login_as(client, ref)

    resp = client.get(f"/{t.url}/get-points")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is False
    assert data["error"] == "Match ID required"
