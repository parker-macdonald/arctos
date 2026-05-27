"""Tests for the optional TeamRegistration.shortname field."""

from __future__ import annotations

import pytest

from app.exceptions import ValidationError
from app.models import TeamRegistration, constants


@pytest.mark.unit
def test_team_registration_accepts_max_len_shortname(test_db, tournament, team):
    """A SHORTNAME_LEN shortname is accepted; the column round-trips."""
    reg = TeamRegistration(
        event=tournament.url, team=team.id, pseudonym="Pseudo", shortname="x" * constants.SHORTNAME_LEN
    )
    from models import db

    db.session.add(reg)
    db.session.commit()
    assert reg.shortname == "x" * constants.SHORTNAME_LEN


@pytest.mark.unit
def test_team_registration_rejects_too_long_shortname(test_db, team):
    """Length validator from issue #28 rejects a too-long shortname."""
    reg = TeamRegistration(team=team.id, pseudonym="Pseudo")
    with pytest.raises(ValidationError) as exc:
        reg.shortname = "x" * (constants.SHORTNAME_LEN + 1)
    assert "shortname" in str(exc.value)
    assert str(constants.SHORTNAME_LEN) in str(exc.value)


@pytest.mark.unit
def test_team_registration_accepts_null_shortname(test_db, tournament, team):
    """NULL shortname is valid (column is nullable)."""
    reg = TeamRegistration(event=tournament.url, team=team.id, pseudonym="Pseudo")
    from models import db

    db.session.add(reg)
    db.session.commit()
    assert reg.shortname is None


@pytest.mark.unit
def test_register_team_persists_shortname(test_db, tournament, team):
    from app.services.registration_service import RegistrationService
    from app.services._common import Scope

    res = RegistrationService.register_team(
        Scope.event(tournament.url),
        team.id,
        pseudonym="Pseudo",
        shortname="BCS",
    )
    assert res.is_ok(), res.unwrap_err()
    reg = res.unwrap()
    assert reg.shortname == "BCS"


@pytest.mark.unit
def test_register_team_normalises_empty_shortname_to_none(test_db, tournament, team):
    from app.services.registration_service import RegistrationService
    from app.services._common import Scope

    res = RegistrationService.register_team(
        Scope.event(tournament.url),
        team.id,
        pseudonym="Pseudo",
        shortname="",
    )
    assert res.is_ok()
    assert res.unwrap().shortname is None


@pytest.mark.unit
def test_register_team_normalises_whitespace_shortname_to_none(test_db, tournament, team):
    from app.services.registration_service import RegistrationService
    from app.services._common import Scope

    res = RegistrationService.register_team(
        Scope.event(tournament.url),
        team.id,
        pseudonym="Pseudo",
        shortname="   ",
    )
    assert res.is_ok()
    assert res.unwrap().shortname is None


@pytest.mark.unit
def test_register_team_normalises_none_shortname(test_db, tournament, team):
    from app.services.registration_service import RegistrationService
    from app.services._common import Scope

    res = RegistrationService.register_team(
        Scope.event(tournament.url),
        team.id,
        pseudonym="Pseudo",
        shortname=None,
    )
    assert res.is_ok()
    assert res.unwrap().shortname is None


@pytest.mark.unit
def test_register_team_trims_shortname_whitespace(test_db, tournament, team):
    from app.services.registration_service import RegistrationService
    from app.services._common import Scope

    res = RegistrationService.register_team(
        Scope.event(tournament.url),
        team.id,
        pseudonym="Pseudo",
        shortname="  BCS  ",
    )
    assert res.is_ok()
    assert res.unwrap().shortname == "BCS"
