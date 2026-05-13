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


@pytest.mark.unit
def test_player_name_accepts_value_exactly_at_short_name_len(test_db):
    """A 100-char name (exactly SHORT_NAME_LEN) is accepted."""
    player = Player(id="lenok1", pw_hash="dummy")
    player.name = "x" * 100  # should not raise
    assert player.name == "x" * 100


@pytest.mark.unit
def test_player_name_accepts_value_shorter_than_short_name_len(test_db):
    """A short name is accepted unchanged."""
    player = Player(id="lenok2", pw_hash="dummy")
    player.name = "Alice"
    assert player.name == "Alice"


@pytest.mark.unit
def test_nullable_string_accepts_none(test_db):
    """Assigning None to a nullable String column does not raise."""
    player = Player(id="lennone", name="N", pw_hash="dummy")
    player.location = None  # Player.location is nullable String(SHORT_NAME_LEN)
    assert player.location is None


@pytest.mark.unit
def test_validator_passes_through_non_string_values(test_db):
    """The length validator only checks strings; other types are not its concern."""
    player = Player(id="lenint", name="N", pw_hash="dummy")
    # Assigning an int to a String column is a type misuse, but the length
    # validator should not be what catches it - it should be a no-op so that
    # SQLAlchemy's own type handling owns the error path.
    player.location = 12345  # must not raise ValidationError
    assert player.location == 12345


@pytest.mark.unit
def test_text_columns_are_not_length_limited(test_db):
    """Text columns have no declared length and are never rejected by the validator."""
    player = Player(id="lentext", name="N", pw_hash="dummy")
    long_bio = "x" * 100_000  # Player.bio is db.Text - no length
    player.bio = long_bio  # must not raise
    assert player.bio == long_bio


@pytest.mark.unit
def test_every_mapped_string_column_rejects_overflow(test_db):
    """Sweep every registered mapper and confirm each String(N) column rejects N+1 chars.

    This is the future-proofing guard: any String column added to a model in
    future will be covered automatically without per-column test maintenance.
    The test does not write to the database - it only assigns to an in-memory
    instance and asserts the validator fires.
    """
    from sqlalchemy import String
    from sqlalchemy.orm import instrumentation as sa_instrumentation

    from app.models import db

    checked: list[tuple[str, str, int]] = []
    for mapper in db.Model.registry.mappers:
        cls = mapper.class_
        for col_attr in mapper.column_attrs:
            col = col_attr.columns[0]
            if not (isinstance(col.type, String) and col.type.length):
                continue
            instance = sa_instrumentation.manager_of_class(cls).new_instance()
            field = col_attr.key
            n = col.type.length
            with pytest.raises(ValidationError) as exc:
                setattr(instance, field, "x" * (n + 1))
            msg = str(exc.value)
            assert field in msg, f"{cls.__name__}.{field}: field name missing from error"
            assert str(n) in msg, f"{cls.__name__}.{field}: max length missing from error"
            checked.append((cls.__name__, field, n))

    # Sanity floor: the codebase has ~103 String(N) columns; a regression that
    # silently dropped a large chunk should fail here, not just an empty sweep.
    assert len(checked) >= 80, f"expected coverage sweep to hit many columns, got {checked!r}"
