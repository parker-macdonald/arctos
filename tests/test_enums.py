import pytest

from app.domain.enums import (
    MatchStatus,
    RegistrationStatus,
    ScheduleType,
    SetType,
    WinnerSide,
    parse_enum,
)


@pytest.mark.unit
def test_parse_enum_accepts_valid_strings():
    assert parse_enum(MatchStatus, "COMPLETED").unwrap() == MatchStatus.COMPLETED
    assert parse_enum(ScheduleType, "SAFE").unwrap() == ScheduleType.SAFE
    assert parse_enum(ScheduleType, "FAST").unwrap() == ScheduleType.FAST
    assert parse_enum(SetType, "SETS").unwrap() == SetType.SETS
    assert parse_enum(WinnerSide, "TEAM1").unwrap() == WinnerSide.TEAM1
    assert (
        parse_enum(RegistrationStatus, "CONFIRMED").unwrap()
        == RegistrationStatus.CONFIRMED
    )


@pytest.mark.unit
def test_parse_enum_returns_none_for_invalid_values():
    assert parse_enum(MatchStatus, "nope").is_null()
    assert parse_enum(ScheduleType, 12345).is_null()
    assert parse_enum(WinnerSide, None).is_null()


@pytest.mark.unit
def test_parse_enum_is_idempotent():
    assert (
        parse_enum(MatchStatus, MatchStatus.IN_PROGRESS).unwrap()
        == MatchStatus.IN_PROGRESS
    )
