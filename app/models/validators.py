"""Automatic validation hooks for SQLAlchemy string-backed model fields.

Importing this module registers ``mapper_configured`` listeners. For every ORM
mapper that is configured, the length installer walks ``mapper.column_attrs``
and, for each column whose type is a
:class:`sqlalchemy.String` with a non-``None`` ``length``, installs a
``set`` event listener on the instrumented attribute. The ``set`` listener
checks ``len(value)`` against the column's declared length and raises
:class:`app.exceptions.ValidationError` if the value exceeds the limit.

A second installer attaches shared URL-slug validation to the ORM fields that
store league and event slugs.

The module must be imported before any mapper is *configured* (mapper
configuration is lazy and is normally triggered by the first query or by
``configure_mappers()``). Importing it at the top of
:mod:`app.models.__init__` - before the individual model modules are
imported - is sufficient.

Behaviour summary:

* ``str`` values longer than the column length -> ``ValidationError``.
* ``str`` values shorter than or exactly equal to the column length -> pass.
* ``None`` -> pass (nullability is enforced separately by the DB column).
* Non-string values -> pass through; SQLAlchemy's own type handling owns
  type coercion.
* ``Text`` columns -> pass; ``Text`` has no declared length.
"""

from __future__ import annotations

import re
from typing import Any, Callable

from sqlalchemy import String, event
from sqlalchemy.orm import Mapper

from app.exceptions import ValidationError

URL_SLUG_ALLOWED_HINT = "URL slugs may only contain letters, numbers, or -_~."
_URL_SLUG_PATTERN = re.compile(r"^[A-Za-z0-9\.\_\~\-]+$")


def is_valid_url_slug(value: str) -> bool:
    """Return whether ``value`` is a non-empty slug with only allowed characters."""

    return bool(_URL_SLUG_PATTERN.fullmatch(value))


def _make_length_validator(field_name: str, max_length: int) -> Callable[..., Any]:
    """Build a ``set``-event handler that rejects over-long string values.

    Args:
        field_name: The SQLAlchemy attribute key, used in the error message.
        max_length: The declared column length to enforce.

    Returns:
        A callable suitable for use with ``event.listen(..., 'set', ..., retval=True)``.
    """

    def _validate(target: Any, value: Any, oldvalue: Any, initiator: Any) -> Any:
        if isinstance(value, str) and len(value) > max_length:
            raise ValidationError(f"{field_name} exceeds maximum length of {max_length} characters (got {len(value)})")
        return value

    return _validate


def _make_url_slug_validator(field_name: str) -> Callable[..., Any]:
    """Build a ``set``-event handler that enforces the shared URL slug rules."""

    def _validate(target: Any, value: Any, oldvalue: Any, initiator: Any) -> Any:
        if isinstance(value, str) and value and not is_valid_url_slug(value):
            raise ValidationError(f"{field_name} may only contain letters, numbers, or -_~.")
        return value

    return _validate


@event.listens_for(Mapper, "mapper_configured")
def _install_string_length_validators(mapper: Mapper, cls: type) -> None:
    """Install per-column length validators on ``cls`` when its mapper is configured.

    Scans every column-mapped attribute on the mapper; for each one backed by a
    ``String`` column with a non-``None`` ``length``, attaches a ``set`` event
    listener to the instrumented attribute.

    Args:
        mapper: The SQLAlchemy ``Mapper`` that has just finished configuring.
        cls: The mapped class (the ORM model).
    """
    for col_attr in mapper.column_attrs:
        col = col_attr.columns[0]
        if isinstance(col.type, String) and col.type.length:
            event.listen(
                getattr(cls, col_attr.key),
                "set",
                _make_length_validator(col_attr.key, col.type.length),
                retval=True,
            )


@event.listens_for(Mapper, "mapper_configured")
def _install_url_slug_validators(mapper: Mapper, cls: type) -> None:
    """Install shared URL-slug validators on ``cls`` when its mapper is configured."""

    for col_attr in mapper.column_attrs:
        col = col_attr.columns[0]
        if isinstance(col.type, String) and col_attr.key in {"url", "event", "league_id"}:
            event.listen(
                getattr(cls, col_attr.key),
                "set",
                _make_url_slug_validator(col_attr.key),
                retval=True,
            )
