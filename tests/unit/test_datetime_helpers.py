from datetime import datetime, timezone, timedelta

import pytest


@pytest.mark.unit
def test_now_utc_naive_returns_naive_datetime():
    from app.utils.datetime_helpers import now_utc_naive

    result = now_utc_naive()
    assert isinstance(result, datetime)
    assert result.tzinfo is None


@pytest.mark.unit
def test_now_utc_naive_close_to_actual_now():
    from app.utils.datetime_helpers import now_utc_naive

    expected = datetime.now(timezone.utc).replace(tzinfo=None)
    result = now_utc_naive()
    assert abs(result - expected) < timedelta(seconds=1)
