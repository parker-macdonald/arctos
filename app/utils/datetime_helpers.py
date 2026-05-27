"""
Datetime helper utilities.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

from app.error_values import Null, Option, Some


def normalize_datetime(dt: datetime | None) -> Option[datetime]:
    """Normalise a datetime for JSON serialisation.

    * Naive datetimes are treated as UTC.
    * Microseconds are stripped (sub-second precision is not needed for API
      timestamps).

    Args:
        dt: A :class:`~datetime.datetime` instance, or ``None``.

    Returns:
        :class:`~app.error_values.Some` wrapping the normalised UTC datetime,
        or :class:`~app.error_values.Null` when *dt* is ``None``.
    """
    if dt is None:
        return Null()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return Some(dt.replace(microsecond=0))


def to_aware_utc(dt: datetime | None) -> Option[datetime]:
    """Convert a possibly-naive datetime to a timezone-aware UTC datetime.

    Args:
        dt: A :class:`~datetime.datetime` instance (naive or aware), or
            ``None``.

    Returns:
        :class:`~app.error_values.Some` wrapping the UTC-aware datetime, or
        :class:`~app.error_values.Null` when *dt* is ``None``.
    """
    if dt is None:
        return Null()
    if dt.tzinfo is None:
        return Some(dt.replace(tzinfo=timezone.utc))
    return Some(dt.astimezone(timezone.utc))


def to_iso_z(dt: datetime | None) -> Option[str]:
    """Convert a datetime to a UTC ISO-8601 string ending with ``"Z"``.

    Tolerates naive datetimes by treating them as UTC.

    Args:
        dt: A :class:`~datetime.datetime` instance, or ``None``.

    Returns:
        :class:`~app.error_values.Some` wrapping an ISO string like
        ``"2024-06-01T14:30:00Z"``, or :class:`~app.error_values.Null` when
        *dt* is ``None``.
    """
    match to_aware_utc(dt):
        case Some(d):
            return Some(d.isoformat().replace("+00:00", "Z"))
        case _:
            return Null()


def parse_datetime_local_to_utc(dt_string: str) -> datetime:
    """Parse a ``datetime-local`` HTML input string and convert it to UTC.

    The input is assumed to represent a time in the server's local timezone
    (as set by the OS).  The result is a timezone-naive datetime representing
    UTC time, suitable for storage in the database.

    Args:
        dt_string: A string in ``"YYYY-MM-DDTHH:MM"`` format as produced by
            ``<input type="datetime-local">``.

    Returns:
        A naive :class:`~datetime.datetime` in UTC.
    """
    # Parse as naive datetime (assumed to be server-local)
    naive_dt = datetime.strptime(dt_string, "%Y-%m-%dT%H:%M")
    # Get server's local timezone
    import time

    local_tz_offset = time.timezone if (time.daylight == 0) else time.altzone
    local_tz = timezone(timedelta(seconds=-local_tz_offset))
    # Make it timezone-aware in server's local timezone
    local_dt = naive_dt.replace(tzinfo=local_tz)
    # Convert to UTC and strip timezone info for storage
    utc_dt = local_dt.astimezone(timezone.utc)
    return utc_dt.replace(tzinfo=None)


def now_utc_naive() -> datetime:
    """Return the current time as a naive UTC datetime (``tzinfo=None``).

    Use this everywhere the codebase currently writes the
    ``datetime.now(timezone.utc).replace(tzinfo=None)`` incantation. The
    DB stores naive UTC values; this helper is the single source of truth
    for that conversion.

    Returns:
        Naive ``datetime`` representing the current UTC moment.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)
