"""Tests for app.utils.camera_helpers."""

from datetime import datetime, timezone

import pytest

from app.utils.camera_helpers import calculate_stream_timestamp


@pytest.mark.unit
def test_calculate_stream_timestamp_iso_strings_returns_seconds():
    result = calculate_stream_timestamp(
        "2026-01-01T00:00:10Z",
        "2026-01-01T00:00:00Z",
    )
    assert result == 10.0


@pytest.mark.unit
def test_calculate_stream_timestamp_datetime_arg_works():
    point_dt = datetime(2026, 1, 1, 0, 0, 30, tzinfo=timezone.utc)
    result = calculate_stream_timestamp(point_dt, "2026-01-01T00:00:00Z")
    assert result == 30.0


@pytest.mark.unit
def test_calculate_stream_timestamp_negative_diff_returns_none():
    """Point before stream start - the existing semantics return None."""
    result = calculate_stream_timestamp(
        "2026-01-01T00:00:00Z",
        "2026-01-01T00:00:10Z",
    )
    assert result is None


@pytest.mark.unit
def test_calculate_stream_timestamp_none_point_returns_none():
    assert calculate_stream_timestamp(None, "2026-01-01T00:00:00Z") is None


@pytest.mark.unit
def test_calculate_stream_timestamp_none_stream_returns_none():
    assert calculate_stream_timestamp("2026-01-01T00:00:10Z", None) is None
