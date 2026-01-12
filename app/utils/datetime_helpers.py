"""
Datetime helper utilities.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

from app.error_values import Null, Option, Some


def normalize_datetime(dt: datetime | None) -> Option[datetime]:
    """
    Normalize a datetime for JSON output:
    - If naive, assume UTC
    - Remove microseconds
    """
    if dt is None:
        return Null()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return Some(dt.replace(microsecond=0))


def to_aware_utc(dt: datetime | None) -> Option[datetime]:
    """Convert possibly-naive datetime to timezone-aware UTC datetime."""
    if dt is None:
        return Null()
    if dt.tzinfo is None:
        return Some(dt.replace(tzinfo=timezone.utc))
    return Some(dt.astimezone(timezone.utc))


def to_iso_z(dt: datetime | None) -> Option[str]:
    """Convert datetime to ISO string with 'Z' suffix (UTC), tolerant of naive dt."""
    match to_aware_utc(dt):
        case Some(d):
            return Some(d.isoformat().replace("+00:00", "Z"))
        case _:
            return Null()


def parse_datetime_local_to_utc(dt_string: str) -> datetime:
    """
    Parse a datetime-local input string (YYYY-MM-DDTHH:MM) and convert to UTC.
    
    Assumes the input represents a time in the server's local timezone.
    Returns a naive datetime representing UTC time (for storage in DB).
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
