import pytest

from app import create_app
from app.exceptions import ValidationError


@pytest.mark.unit
def test_arctos_error_handler_returns_json_for_api_paths():
    app = create_app(config={"TESTING": True, "SECRET_KEY": "test"})

    @app.get("/api/test-error")
    def _api_error():
        raise ValidationError("bad input")

    client = app.test_client()
    resp = client.get("/api/test-error")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is False
    assert data["error"] == "bad input"


@pytest.mark.unit
def test_arctos_error_handler_redirects_for_html_paths():
    app = create_app(config={"TESTING": True, "SECRET_KEY": "test"})

    @app.get("/test-error")
    def _html_error():
        raise ValidationError("bad input")

    client = app.test_client()
    resp = client.get("/test-error", follow_redirects=False)
    # Redirect to / (or referrer). Flask redirect status.
    assert resp.status_code in (301, 302, 303, 307, 308)
