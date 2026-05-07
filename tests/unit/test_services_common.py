"""Unit tests for app.services._common helpers."""

import pytest

from app.error_values import Err, Ok
from app.exceptions import ArctosError


@pytest.mark.unit
def test_get_tournament_or_err_returns_ok_when_found(app, test_db, tournament):
    from app.services._common import get_tournament_or_err

    res = get_tournament_or_err(tournament.url)
    assert isinstance(res, Ok)
    assert res.val.url == tournament.url


@pytest.mark.unit
def test_get_tournament_or_err_returns_err_when_missing(app, test_db):
    from app.services._common import get_tournament_or_err

    res = get_tournament_or_err("does-not-exist")
    assert isinstance(res, Err)
    assert isinstance(res.val, ArctosError)
    assert res.val.status_code == 404
    assert res.val.public is True
