"""Edit-time resolution of ``MatchName::winner`` / ``::loser`` references.

When a user sets a match's ``team1_initial`` (or a refs slot) to a winner /
loser reference, the resolved team-id cache (``team1`` / ``team2`` / refs
``team_id``) should be filled in immediately when the referenced match is
already decided. Without this, the schedule UI keeps showing the literal
reference token even after the source match has a winner.

Covers ``resolve_match_winner_loser_ref``, ``resolve_team_slot``, and
``resolve_single_ref_slot``.
"""

from __future__ import annotations

import pytest

from app.domain.enums import MatchStatus, ScheduleType, WinnerSide
from app.utils.helpers import resolve_match_winner_loser_ref
from app.utils.match_ref_resolution import resolve_single_ref_slot, resolve_team_slot
from models import Match, db


def _decided_match(tournament_url: str, *, name: str, t1: str, t2: str, winner: WinnerSide) -> Match:
    m = Match(
        name=name,
        event=tournament_url,
        schedule_type=ScheduleType.STATIC,
        status=MatchStatus.COMPLETED,
        nominal_length=60,
        team1=t1,
        team2=t2,
        match_winner=winner,
    )
    db.session.add(m)
    db.session.flush()
    return m


def _undecided_match(tournament_url: str, *, name: str, t1: str, t2: str) -> Match:
    m = Match(
        name=name,
        event=tournament_url,
        schedule_type=ScheduleType.STATIC,
        status=MatchStatus.NOT_STARTED,
        nominal_length=60,
        team1=t1,
        team2=t2,
    )
    db.session.add(m)
    db.session.flush()
    return m


@pytest.mark.unit
def test_resolve_match_winner_loser_ref_decided(app, test_db, tournament, seeded_teams):
    """Both ``::winner`` and ``::loser`` resolve when the source match is decided."""
    with app.app_context():
        _decided_match(tournament.url, name="Final", t1="team_1", t2="team_2", winner=WinnerSide.TEAM1)
        assert resolve_match_winner_loser_ref("Final::winner", tournament.url) == "team_1"
        assert resolve_match_winner_loser_ref("Final::loser", tournament.url) == "team_2"


@pytest.mark.unit
def test_resolve_match_winner_loser_ref_undecided_returns_none(app, test_db, tournament, seeded_teams):
    """An undecided match yields ``None`` so the cache stays empty until completion."""
    with app.app_context():
        _undecided_match(tournament.url, name="Semi", t1="team_1", t2="team_2")
        assert resolve_match_winner_loser_ref("Semi::winner", tournament.url) is None
        assert resolve_match_winner_loser_ref("Semi::loser", tournament.url) is None


@pytest.mark.unit
def test_resolve_match_winner_loser_ref_unknown_match(app, test_db, tournament):
    """Reference to a non-existent match returns ``None``."""
    with app.app_context():
        assert resolve_match_winner_loser_ref("Ghost::winner", tournament.url) is None


@pytest.mark.unit
def test_resolve_match_winner_loser_ref_non_ref_token(app, test_db, tournament):
    """Plain team ids and tag refs are not winner/loser refs — return ``None``."""
    with app.app_context():
        assert resolve_match_winner_loser_ref("team_1", tournament.url) is None
        assert resolve_match_winner_loser_ref("tag::PoolA", tournament.url) is None


@pytest.mark.unit
def test_resolve_team_slot_returns_winner_when_decided(app, test_db, tournament, seeded_teams):
    """``resolve_team_slot`` (used by team1/team2) populates the cache."""
    with app.app_context():
        _decided_match(tournament.url, name="QF", t1="team_1", t2="team_2", winner=WinnerSide.TEAM2)
        team_id, initial = resolve_team_slot("QF::winner", tournament.url)
        assert team_id == "team_2"
        # Display token preserves the original reference so the operator still sees the chip.
        assert initial == "QF::winner"


@pytest.mark.unit
def test_resolve_team_slot_undecided_keeps_initial_only(app, test_db, tournament, seeded_teams):
    """Undecided ref leaves the cached team id empty but preserves the display token."""
    with app.app_context():
        _undecided_match(tournament.url, name="QF", t1="team_1", t2="team_2")
        team_id, initial = resolve_team_slot("QF::winner", tournament.url)
        assert team_id is None
        assert initial == "QF::winner"


@pytest.mark.unit
def test_resolve_single_ref_slot_returns_loser_when_decided(app, test_db, tournament, seeded_teams):
    """The refs path resolves ``::loser`` the same way."""
    with app.app_context():
        _decided_match(tournament.url, name="SF", t1="team_1", t2="team_2", winner=WinnerSide.TEAM1)
        resolved, initial = resolve_single_ref_slot("SF::loser", tournament.url)
        assert resolved == "team_2"
        assert initial == "SF::loser"


@pytest.mark.unit
def test_resolve_single_ref_slot_undecided_keeps_token(app, test_db, tournament, seeded_teams):
    """Undecided ref slot stores the token but no resolved id."""
    with app.app_context():
        _undecided_match(tournament.url, name="SF", t1="team_1", t2="team_2")
        resolved, initial = resolve_single_ref_slot("SF::loser", tournament.url)
        assert resolved == ""
        assert initial == "SF::loser"
