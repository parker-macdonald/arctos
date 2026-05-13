"""Tests for automatic string length validation on SQLAlchemy String columns.

These tests verify that assigning an over-long value to any String(N) ORM
attribute raises ValidationError before the value can reach the database.
The validators are installed once, at import time, by app/models/validators.py.
"""

from __future__ import annotations

import pytest

from app.exceptions import ValidationError
from models import Player


@pytest.mark.unit
def test_player_name_rejects_value_longer_than_short_name_len(test_db):
    """Assigning a 101-char name to Player.name (SHORT_NAME_LEN=100) raises ValidationError."""
    player = Player(id="lenchk", pw_hash="dummy")
    with pytest.raises(ValidationError) as exc:
        player.name = "x" * 101
    assert "name" in str(exc.value)
    assert "100" in str(exc.value)
