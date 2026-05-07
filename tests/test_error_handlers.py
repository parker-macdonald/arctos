"""Tests for the Flask ArctosError handler (JSON vs. redirect behaviour)."""

import pytest

from app import create_app
from app.exceptions import NotFoundError, UnauthorizedError, ValidationError


@pytest.mark.unit
def test_arctos_validation_error_returns_400_on_api_path():
    """ValidationError on /_api/* should serialise as JSON with HTTP 400."""
    app = create_app(config={"TESTING": True, "SECRET_KEY": "test"})

    @app.get("/_api/test-validation")
    def _api_validation():
        raise ValidationError("bad input")

    client = app.test_client()
    resp = client.get("/_api/test-validation")
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["success"] is False
    assert data["error"] == "bad input"


@pytest.mark.unit
def test_arctos_not_found_error_returns_404_on_api_path():
    """NotFoundError on /_api/* should serialise as JSON with HTTP 404."""
    app = create_app(config={"TESTING": True, "SECRET_KEY": "test"})

    @app.get("/_api/test-notfound")
    def _api_notfound():
        raise NotFoundError("missing thing")

    client = app.test_client()
    resp = client.get("/_api/test-notfound")
    assert resp.status_code == 404
    data = resp.get_json()
    assert data["success"] is False
    assert data["error"] == "missing thing"


@pytest.mark.unit
def test_arctos_unauthorized_error_returns_403_on_api_path():
    """UnauthorizedError on /_api/* should serialise as JSON with HTTP 403."""
    app = create_app(config={"TESTING": True, "SECRET_KEY": "test"})

    @app.get("/_api/test-unauth")
    def _api_unauth():
        raise UnauthorizedError("nope")

    client = app.test_client()
    resp = client.get("/_api/test-unauth")
    assert resp.status_code == 403
    data = resp.get_json()
    assert data["success"] is False
    assert data["error"] == "nope"


@pytest.mark.unit
def test_arctos_error_handler_redirects_for_html_paths():
    """Errors raised on non-API paths trigger a flash-and-redirect response."""
    app = create_app(config={"TESTING": True, "SECRET_KEY": "test"})

    @app.get("/test-error")
    def _html_error():
        raise ValidationError("bad input")

    client = app.test_client()
    resp = client.get("/test-error", follow_redirects=False)
    assert resp.status_code in (301, 302, 303, 307, 308)
