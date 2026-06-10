"""Extra soft-validation warnings: missing team and duplicate team within a match."""

from __future__ import annotations

import pytest

from app.domain.enums import MatchStatus, ScheduleType
from app.services.dual_write import set_match_referees
from app.utils.scheduling import validate_match_warnings
from models import Match, db


def _mk(tournament_url: str, name: str, *, schedule_type=ScheduleType.STATIC, **kwargs) -> Match:
    m = Match(
        name=name,
        event=tournament_url,
        schedule_type=schedule_type,
        status=MatchStatus.NOT_STARTED,
        nominal_length=60,
        field="F1",
        **kwargs,
    )
    db.session.add(m)
    db.session.flush()
    return m


@pytest.mark.unit
def test_missing_team1_is_flagged(app, test_db, tournament, seeded_teams):
    with app.app_context():
        _mk(tournament.url, "M1", team1=None, team1_initial=None, team2="team_2", team2_initial="team_2")
        db.session.commit()
        warnings = validate_match_warnings(tournament.url)
        msgs = [w for w in warnings if w["kind"] == "missing_team"]
        assert any("M1" in w["matches"] and "team1" in w["message"] for w in msgs)


@pytest.mark.unit
def test_missing_team2_is_flagged(app, test_db, tournament, seeded_teams):
    with app.app_context():
        _mk(tournament.url, "M2", team1="team_1", team1_initial="team_1", team2=None, team2_initial=None)
        db.session.commit()
        warnings = validate_match_warnings(tournament.url)
        msgs = [w for w in warnings if w["kind"] == "missing_team"]
        assert any("M2" in w["matches"] and "team2" in w["message"] for w in msgs)


@pytest.mark.unit
def test_unresolved_match_ref_is_not_missing(app, test_db, tournament, seeded_teams):
    """team1=None but team1_initial='Other::winner' is pending, not missing."""
    with app.app_context():
        _mk(
            tournament.url, "Pending", team1=None, team1_initial="Other::winner", team2="team_2", team2_initial="team_2"
        )
        db.session.commit()
        warnings = validate_match_warnings(tournament.url)
        msgs = [w for w in warnings if w["kind"] == "missing_team"]
        # Should not flag — the placeholder will fill in once Other completes.
        assert not any("Pending" in w["matches"] for w in msgs)


@pytest.mark.unit
def test_break_match_with_no_teams_is_not_flagged(app, test_db, tournament):
    """BREAK / JOIN matches don't have teams — no missing_team warnings."""
    with app.app_context():
        _mk(tournament.url, "Lunch", schedule_type=ScheduleType.BREAK, team1=None, team2=None)
        db.session.commit()
        warnings = validate_match_warnings(tournament.url)
        assert not any(w["kind"] == "missing_team" for w in warnings)


@pytest.mark.unit
def test_duplicate_team1_team2_flagged(app, test_db, tournament, seeded_teams):
    with app.app_context():
        _mk(
            tournament.url,
            "Same",
            team1="team_1",
            team1_initial="team_1",
            team2="team_1",
            team2_initial="team_1",
        )
        db.session.commit()
        warnings = validate_match_warnings(tournament.url)
        dups = [w for w in warnings if w["kind"] == "duplicate_team"]
        assert len(dups) == 1
        assert "Same" in dups[0]["matches"]
        assert "team1" in dups[0]["message"] and "team2" in dups[0]["message"]


@pytest.mark.unit
def test_duplicate_team_in_team1_and_refs(app, test_db, tournament, seeded_teams):
    with app.app_context():
        m = _mk(
            tournament.url,
            "RefDup",
            team1="team_1",
            team1_initial="team_1",
            team2="team_2",
            team2_initial="team_2",
        )
        db.session.flush()
        set_match_referees(m, ["team_1"], ["team_1"])
        db.session.commit()
        warnings = validate_match_warnings(tournament.url)
        dups = [w for w in warnings if w["kind"] == "duplicate_team"]
        assert len(dups) == 1
        assert "team1" in dups[0]["message"]
        assert "refs[0]" in dups[0]["message"]


@pytest.mark.unit
def test_duplicate_via_match_winner_token_in_two_slots(app, test_db, tournament, seeded_teams):
    """Two slots with the same unresolved Match::winner token should flag as duplicate."""
    with app.app_context():
        _mk(
            tournament.url,
            "Twin",
            team1=None,
            team1_initial="Final::winner",
            team2=None,
            team2_initial="Final::winner",
        )
        db.session.commit()
        warnings = validate_match_warnings(tournament.url)
        dups = [w for w in warnings if w["kind"] == "duplicate_team"]
        assert len(dups) == 1
        assert "Final::winner" in dups[0]["message"]


@pytest.mark.unit
def test_no_warnings_for_clean_match(app, test_db, tournament, seeded_teams):
    """Sanity: a match with two distinct registered teams produces neither warning."""
    with app.app_context():
        from models import TeamRegistration
        from app.domain.enums import TeamRegistrationStatus

        for tid in ("team_1", "team_2"):
            db.session.add(
                TeamRegistration(
                    event=tournament.url,
                    team=tid,
                    pseudonym=tid,
                    status=TeamRegistrationStatus.CONFIRMED,
                )
            )
        _mk(
            tournament.url,
            "Clean",
            team1="team_1",
            team1_initial="team_1",
            team2="team_2",
            team2_initial="team_2",
        )
        db.session.commit()
        warnings = validate_match_warnings(tournament.url)
        clean = [w for w in warnings if w["kind"] in ("missing_team", "duplicate_team") and "Clean" in w["matches"]]
        assert clean == []
