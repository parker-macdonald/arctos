"""Tests for apply_match_dependencies (winner/loser placeholder resolution)."""

import pytest

from app.domain.enums import MatchStatus
from app.services.dual_write import (
    get_match_ref_initials,
    get_match_ref_team_ids,
    set_match_referees,
)
from app.utils.dependencies import apply_match_dependencies
from models import Match, db


@pytest.mark.unit
def test_apply_match_dependencies_substitutes_winner_loser_and_refs(test_db, tournament, seeded_teams):
    """apply_match_dependencies replaces winner/loser placeholders in dependent matches."""
    tournament_url = tournament.url
    completed = Match(
        name="Match A",
        event=tournament_url,
        schedule_type="SAFE",
        status=MatchStatus.COMPLETED,
        team1="team_1",
        team2="team_2",
        match_winner="TEAM1",
    )
    dependent = Match(
        name="Match B",
        event=tournament_url,
        schedule_type="SAFE",
        status=MatchStatus.NOT_STARTED,
        team1=None,
        team2=None,
        team1_initial="Match A::winner",
        team2_initial="Match A::loser",
    )
    db.session.add_all([completed, dependent])
    db.session.flush()
    # team3 is a real team (seeded_teams); the surrounding slots hold winner/loser placeholders.
    set_match_referees(
        dependent,
        ["", "team3", ""],
        ["Match A::winner", "team3", "Match A::loser"],
    )
    db.session.commit()

    apply_match_dependencies(tournament_url, completed)

    dep = Match.query.filter_by(event=tournament_url, name="Match B").first()
    assert dep is not None
    assert dep.team1 == "team_1"
    assert dep.team2 == "team_2"
    assert get_match_ref_team_ids(dep) == ["team_1", "team3", "team_2"]
    assert get_match_ref_initials(dep) == ["Match A::winner", "team3", "Match A::loser"]


@pytest.mark.unit
def test_apply_match_dependencies_noop_when_no_winner(test_db, tournament, seeded_teams):
    tournament_url = tournament.url
    completed = Match(
        name="Match A",
        event=tournament_url,
        schedule_type="SAFE",
        status=MatchStatus.COMPLETED,
        team1="team_1",
        team2="team_2",
        match_winner=None,
    )
    dependent = Match(
        name="Match B",
        event=tournament_url,
        schedule_type="SAFE",
        status=MatchStatus.NOT_STARTED,
        team1=None,
        team2=None,
        team1_initial="Match A::winner",
    )
    db.session.add_all([completed, dependent])
    db.session.commit()

    apply_match_dependencies(tournament_url, completed)
    dep = Match.query.filter_by(event=tournament_url, name="Match B").first()
    assert dep is not None
    assert dep.team1 is None
