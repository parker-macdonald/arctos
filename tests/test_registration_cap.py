"""Tests for n_max_teams cap enforcement."""

import pytest
from datetime import datetime, timezone

from app.domain.enums import TeamRegistrationStatus
from app.error_values import Err
from app.services.registration_service import RegistrationService
from models import Team, TeamRegistration, Tournament, db
from tests.utils import make_registrable_config


@pytest.fixture
def cap_setup(test_db):
    """Tournament with n_max_teams=2 and three teams that want to register."""
    rc = make_registrable_config(team_registration_open=True)
    rc.n_max_teams = 2
    db.session.commit()

    now = datetime.now(timezone.utc)
    t = Tournament(
        url="capt",
        name="Cap Test",
        registrable_config_id=rc.id,
        start_date=now,
        end_date=now,
    )
    db.session.add(t)

    teams = []
    for i in range(3):
        team = Team(id=f"team{i}", name=f"Team {i}", pw_hash="x", phone="1")
        team.set_password("pw")
        db.session.add(team)
        teams.append(team)
    db.session.commit()
    for team in teams:
        db.session.refresh(team)
    return {"tournament": t, "teams": teams}


@pytest.mark.integration
def test_register_team_blocks_third_when_cap_is_two(cap_setup):
    """Two registrations succeed; the third returns Err."""
    teams = cap_setup["teams"]

    res1 = RegistrationService.register_team("capt", teams[0].id, "ps0")
    res2 = RegistrationService.register_team("capt", teams[1].id, "ps1")
    res3 = RegistrationService.register_team("capt", teams[2].id, "ps2")

    assert not isinstance(res1, Err), repr(res1)
    assert not isinstance(res2, Err), repr(res2)
    assert isinstance(res3, Err)
    assert "Maximum" in str(res3.val)


@pytest.mark.integration
def test_no_pending_rows_remain_at_rest(cap_setup):
    """After a cap-rejected registration, no PENDING rows persist."""
    teams = cap_setup["teams"]
    RegistrationService.register_team("capt", teams[0].id, "ps0")
    RegistrationService.register_team("capt", teams[1].id, "ps1")
    RegistrationService.register_team("capt", teams[2].id, "ps2")  # rejected

    pending = TeamRegistration.query.filter_by(
        event="capt", status=TeamRegistrationStatus.PENDING
    ).count()
    assert pending == 0
    confirmed = TeamRegistration.query.filter_by(
        event="capt", status=TeamRegistrationStatus.CONFIRMED
    ).count()
    assert confirmed == 2
