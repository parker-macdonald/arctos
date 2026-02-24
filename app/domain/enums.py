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


class MatchNoteTarget(StrEnum):
    TEAM1 = "team1"
    TEAM2 = "team2"
    MATCH = "match"
    PLAYER = "player"


class RegistrationStatus(StrEnum):
    PENDING_TEAM_APPROVAL = "PENDING_TEAM_APPROVAL"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class TeamRegistrationStatus(StrEnum):
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


class MatchStatus(StrEnum):
    """Match statuses.
    NOT_STARTED: initial state

    TIME_FINALIZED: start time will not be pushed back any
    further. match is guaranteed not to be skipped.

    READY_TO_START: all ref and playing teams are known; game will
    start as soon as everyone is present.

    IN_PROGRESS: match has been started but not finished

    COMPLETED: match is done! both start and end stamps exist.

    SKIPPED: match has been skipped (effectively completed). start and
    end stamps are equal and are the time that the match was marked
    skipped.
    """

    NOT_STARTED = "NOT_STARTED"
    TIME_FINALIZED = "TIME_FINALIZED"
    READY_TO_START = "READY_TO_START"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    SKIPPED = "SKIPPED"


class ScheduleType(StrEnum):
    STATIC = "STATIC"
    SAFE = "SAFE"
    FAST = "FAST"
    BREAK = "BREAK"
    JOIN = "JOIN"


class SetType(StrEnum):
    SETS = "SETS"
    STONES = "STONES"


class WinnerSide(StrEnum):
    TEAM1 = "TEAM1"
    TEAM2 = "TEAM2"
