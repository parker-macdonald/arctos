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
    """A 100-char name (exactly SHORT_NAME_LEN) is accepted.

    Guards against an off-by-one regression that changes ``len(value) > N``
    to ``>=`` in the validator.
    """
    player = Player(id="lenok1", pw_hash="dummy")
    player.name = "x" * 100  # must not raise ValidationError


@pytest.mark.unit
def test_nullable_string_accepts_none(test_db):
    """Assigning None to a nullable String column does not raise.

    Exercises the ``isinstance(value, str)`` guard: without it, ``len(None)``
    would raise ``TypeError`` from inside the validator.
    """
    player = Player(id="lennone", name="N", pw_hash="dummy")
    player.location = None  # must not raise ValidationError or TypeError


@pytest.mark.unit
def test_validator_passes_through_non_string_values(test_db):
    """Non-string values bypass the validator entirely.

    Exercises the ``isinstance(value, str)`` guard for non-None, non-str
    inputs. SQLAlchemy's own type handling owns the error path for type
    misuse; the length validator is not it.
    """
    player = Player(id="lenint", name="N", pw_hash="dummy")
    player.location = 12345  # must not raise ValidationError


@pytest.mark.unit
def test_text_columns_are_not_length_limited(test_db):
    """Columns without a declared length (db.Text) are never wired up.

    Exercises the ``col.type.length`` skip in the mapper-walking installer.
    """
    player = Player(id="lentext", name="N", pw_hash="dummy")
    player.bio = "x" * 100_000  # must not raise ValidationError


@pytest.mark.unit
def test_every_mapped_string_column_rejects_overflow(test_db):
    """Sweep every registered mapper and confirm each String(N) column rejects N+1 chars.

    Any String column added to a model in
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

    assert len(checked) >= 80, f"expected coverage sweep to hit many columns, got {checked!r}"
