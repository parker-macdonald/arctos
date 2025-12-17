"""
Domain enums used across routes, services, and models.

These enums are designed to be compatible with the existing database schema,
which stores values as strings.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TypeVar

from app.error_values import Null, Option, Some


TEnum = TypeVar("TEnum", bound=StrEnum)


def parse_enum(enum_cls: type[TEnum], value: object) -> Option[TEnum]:
    """Best-effort parse of an enum from a DB/string value, returning Option."""
    if value is None:
        return Null()
    if isinstance(value, enum_cls):
        return Some(value)
    try:
        return Some(enum_cls(str(value)))
    except Exception:
        return Null()


class RegistrationStatus(StrEnum):
    PENDING_TEAM_APPROVAL = "PENDING_TEAM_APPROVAL"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class MatchStatus(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class ScheduleType(StrEnum):
    STATIC = "STATIC"
    DYNAMIC = "DYNAMIC"
    BREAK = "BREAK"
    JOIN = "JOIN"


class SetType(StrEnum):
    SETS = "SETS"
    STONES = "STONES"


class WinnerSide(StrEnum):
    TEAM1 = "TEAM1"
    TEAM2 = "TEAM2"


