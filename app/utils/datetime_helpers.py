"""
Datetime helper utilities.
"""

from __future__ import annotations

from datetime import datetime, timezone

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
