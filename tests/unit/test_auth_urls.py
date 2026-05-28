"""Unit tests for auth redirect and callback URL helpers."""

import pytest


@pytest.mark.unit
def test_google_callback_uri_uses_request_host(app, test_db):
    from app.routes.auth import _google_callback_uri

    with app.test_request_context("/_api/auth/google/login", base_url="https://events-a.example"):
        assert _google_callback_uri() == "https://events-a.example/_api/auth/google/callback"


@pytest.mark.unit
def test_redirect_to_frontend_preserves_script_root(app, test_db):
    from app.routes.auth import _redirect_to_frontend

    with app.test_request_context(
        "/_api/auth/google/callback",
        base_url="https://events-b.example",
        environ_overrides={"SCRIPT_NAME": "/arctos"},
    ):
        response = _redirect_to_frontend("/auth/google/choose-account-type")
        assert response.location == "/arctos/auth/google/choose-account-type"
