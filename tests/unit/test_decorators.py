"""Unit tests for app.utils.decorators helpers."""

import pytest


@pytest.mark.unit
def test_wants_json_for_json_content_type(app):
    from app.utils.decorators import _wants_json

    with app.test_request_context("/foo", json={"a": 1}):
        from flask import request
        assert _wants_json(request) is True


@pytest.mark.unit
def test_wants_json_for_api_path(app):
    from app.utils.decorators import _wants_json

    with app.test_request_context("/_api/something"):
        from flask import request
        assert _wants_json(request) is True


@pytest.mark.unit
def test_wants_json_for_accept_header(app):
    from app.utils.decorators import _wants_json

    with app.test_request_context("/foo", headers={"Accept": "application/json"}):
        from flask import request
        assert _wants_json(request) is True


@pytest.mark.unit
def test_wants_json_false_for_html_request(app):
    from app.utils.decorators import _wants_json

    with app.test_request_context("/foo", headers={"Accept": "text/html"}):
        from flask import request
        assert _wants_json(request) is False
