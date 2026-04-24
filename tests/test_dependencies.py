"""Tests for apply_match_dependencies (winner/loser placeholder resolution)."""

import pytest

from app.domain.enums import MatchStatus
from app.utils.dependencies import apply_match_dependencies
from models import Match, db


@pytest.mark.unit
def test_apply_match_dependencies_substitutes_winner_loser_and_refs(
    test_db, tournament
):
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
        refs=None,
        team1_initial="Match A::winner",
        team2_initial="Match A::loser",
        refs_initial="Match A::winner, some_ref, Match A::loser",
    )
    db.session.add_all([completed, dependent])
    db.session.commit()

    apply_match_dependencies(tournament_url, completed)

    dep = Match.query.filter_by(event=tournament_url, name="Match B").first()
    assert dep is not None
    assert dep.team1 == "team_1"
    assert dep.team2 == "team_2"
    assert dep.refs is not None
    assert dep.refs == "team_1, some_ref, team_2"


@pytest.mark.unit
def test_apply_match_dependencies_noop_when_no_winner(test_db, tournament):
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
