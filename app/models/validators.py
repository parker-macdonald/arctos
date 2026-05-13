"""Automatic length validation for SQLAlchemy ``String(N)`` columns.

Importing this module registers a single ``mapper_configured`` event
listener. For every ORM mapper that is configured, the listener walks
``mapper.column_attrs`` and, for each column whose type is a
:class:`sqlalchemy.String` with a non-``None`` ``length``, installs a
``set`` event listener on the instrumented attribute. The ``set`` listener
checks ``len(value)`` against the column's declared length and raises
:class:`app.exceptions.ValidationError` if the value exceeds the limit.

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

from typing import Any, Callable

from sqlalchemy import String, event
from sqlalchemy.orm import Mapper

from app.exceptions import ValidationError


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
            raise ValidationError(
                f"{field_name} exceeds maximum length of {max_length} "
                f"characters (got {len(value)})"
            )
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
