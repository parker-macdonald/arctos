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
def test_homepage(client):
    """Test that the homepage loads."""
    response = client.get("/")
    assert response.status_code in [
        200,
        302,
    ]  # 200 OK or 302 redirect if login required
