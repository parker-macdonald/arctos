"""Tests for generate_permission_key and validate_permission_key."""

import pytest
from app.utils.helpers import generate_permission_key, validate_permission_key


@pytest.mark.unit
def test_permission_key(app):
    """generate_permission_key produces a 16-char key; validate_permission_key checks it correctly."""
    k = generate_permission_key("FoW_25")
    assert len(k) == 16, f"expected key of length 16 but got len(key)={len(k)}"
    assert validate_permission_key("FoW_25", k)
    assert not validate_permission_key("FoW-25", k), "expected key not to match because of different url slug"
    assert not validate_permission_key("FoW_25", k, "non-matching secret"), (
        "expected key not to match because of different secret"
    )
