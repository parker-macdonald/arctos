"""
Basic tests for the application to verify the testing framework works.
"""

import pytest


@pytest.mark.unit
def test_app_exists(app):
    """Test that the app exists and is configured."""
    assert app is not None
    assert app.config["TESTING"] is True


@pytest.mark.unit
def test_api_server_time(client):
    """Test that the unauthenticated server-time endpoint responds."""
    response = client.get("/_api/server-time")
    assert response.status_code == 200
