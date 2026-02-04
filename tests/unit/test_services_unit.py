import pytest

from app.error_values import Err, Ok
from app.exceptions import RegistrationClosedError, ValidationError
from app.services.match_service import MatchService
from app.services.registration_service import RegistrationService
from models import Match, Tournament, db
from datetime import datetime, timezone


@pytest.mark.unit
def test_registration_service_register_team_closed_raises(test_db, team):
    t = Tournament(
        url="closed",
        name="Closed",
        start_date=datetime.now(timezone.utc),
        published=True,
        registration_open=False,
    )
    db.session.add(t)
    db.session.commit()

    tm = db.session.merge(team)
    res = RegistrationService.register_team("closed", tm.id, "Pseudonym")
    match res:
        case Err(err):
            assert isinstance(err, RegistrationClosedError)
        case Ok(_):
            raise AssertionError("Expected Err(RegistrationClosedError), got Ok")


@pytest.mark.unit
def test_match_service_overlap_raises_without_mutating_match(
    test_db, tournament, head_ref_player
):
    tournament_url = tournament.url
    ref = db.session.merge(head_ref_player)
    m = Match(
        name="Overlap",
        event=tournament_url,
        schedule_type="SAFE",
        set_type="SETS",
        status="NOT_STARTED",
        nominal_length=60,
        field="Field 1",
    )
    db.session.add(m)
    db.session.commit()

    res = MatchService.start_match(
        tournament_url,
        m.uuid,
        ref,
        team1_players_csv="p1,p2",
        team2_players_csv="p2,p3",
    )
    match res:
        case Err(err):
            assert isinstance(err, ValidationError)
        case Ok(_):
            raise AssertionError("Expected Err(ValidationError), got Ok")

    # Ensure not mutated
    m2 = Match.query.get(m.uuid)
    assert m2.status == "NOT_STARTED"
