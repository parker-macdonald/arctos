"""League-event match validation: registrations, warnings, resolver behaviour.

The match-edit / match-validation paths must treat a team as registered when
the team has a CONFIRMED registration scoped to the parent league of a
league-event tournament. Without this, every team in a league event reads as
"unknown_team" and the match-warnings modal lights up incorrectly.
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone, timedelta

from app.domain.enums import (
    MatchStatus,
    ScheduleType,
    TeamRegistrationStatus,
)
from app.utils.helpers import resolve_team_name_to_id
from app.utils.scheduling import validate_match_warnings
from models import (
    League,
    Match,
    Team,
    TeamRegistration,
    Tournament,
    db,
)
from tests.utils import make_registrable_config


def _make_league_event(url_prefix: str) -> Tournament:
    cfg = make_registrable_config()
    league = League(
        url=f"{url_prefix}-lg",
        name="Test League",
        registrable_config_id=cfg.id,
    )
    db.session.add(league)
    db.session.flush()
    t = Tournament(
        url=f"{url_prefix}-evt",
        name="Test League Event",
        start_date=datetime.now(timezone.utc),
        end_date=datetime.now(timezone.utc) + timedelta(days=1),
        location="L",
        max_field_size=14,
        published=True,
        league_id=league.url,
    )
    db.session.add(t)
    db.session.flush()
    return t


def _register_team_for_league(league_url: str, team_id: str) -> None:
    db.session.add(
        TeamRegistration(
            league_id=league_url,
            team=team_id,
            pseudonym=team_id,
            status=TeamRegistrationStatus.CONFIRMED,
        )
    )
    db.session.flush()


def _register_team_for_event(event_url: str, team_id: str) -> None:
    db.session.add(
        TeamRegistration(
            event=event_url,
            team=team_id,
            pseudonym=team_id,
            status=TeamRegistrationStatus.CONFIRMED,
        )
    )
    db.session.flush()


@pytest.mark.unit
def test_resolve_team_name_to_id_league_scope(app, test_db):
    """A team registered to the league counts as registered for an event under that league."""
    with app.app_context():
        team = Team(id="lg_team_1", name="LG Team 1", pw_hash="x")
        db.session.add(team)
        db.session.flush()

        t = _make_league_event("rstn-league")
        _register_team_for_league(t.league_id, team.id)

        team_id, _ = resolve_team_name_to_id("lg_team_1", t.url)
        assert team_id == "lg_team_1"


@pytest.mark.unit
def test_resolve_team_name_to_id_unregistered_team(app, test_db):
    """A team that exists but isn't registered (event or league) returns no id."""
    with app.app_context():
        team = Team(id="orphan_team", name="Orphan", pw_hash="x")
        db.session.add(team)
        db.session.flush()

        t = _make_league_event("rstn-orphan")
        team_id, initial = resolve_team_name_to_id("orphan_team", t.url)
        assert team_id is None
        assert initial == "orphan_team"


@pytest.mark.unit
def test_validate_match_warnings_does_not_flag_league_registered_teams(app, test_db):
    """Match between two league-registered teams should produce no unknown_team warnings."""
    with app.app_context():
        a = Team(id="lg_a", name="A", pw_hash="x")
        b = Team(id="lg_b", name="B", pw_hash="x")
        db.session.add_all([a, b])
        db.session.flush()

        t = _make_league_event("vmw-league")
        _register_team_for_league(t.league_id, a.id)
        _register_team_for_league(t.league_id, b.id)

        m = Match(
            name="M1",
            event=t.url,
            schedule_type=ScheduleType.STATIC,
            status=MatchStatus.NOT_STARTED,
            team1=a.id,
            team2=b.id,
        )
        db.session.add(m)
        db.session.flush()

        warnings = validate_match_warnings(t.url)
        unknown = [w for w in warnings if w["kind"] == "unknown_team"]
        assert unknown == [], f"Expected no unknown_team warnings, got {unknown!r}"


@pytest.mark.unit
def test_validate_match_warnings_flags_unregistered_team_in_league(app, test_db):
    """A team that exists but has no league registration is correctly flagged."""
    with app.app_context():
        registered = Team(id="reg_team", name="Reg", pw_hash="x")
        unregistered = Team(id="unreg_team", name="Unreg", pw_hash="x")
        db.session.add_all([registered, unregistered])
        db.session.flush()

        t = _make_league_event("vmw-flag")
        _register_team_for_league(t.league_id, registered.id)

        m = Match(
            name="M1",
            event=t.url,
            schedule_type=ScheduleType.STATIC,
            status=MatchStatus.NOT_STARTED,
            team1=registered.id,
            team2=unregistered.id,
        )
        db.session.add(m)
        db.session.flush()

        warnings = validate_match_warnings(t.url)
        unknown = [w for w in warnings if w["kind"] == "unknown_team"]
        # Only the unregistered team should be flagged.
        assert len(unknown) == 1
        assert "unreg_team" in unknown[0]["message"]


@pytest.mark.unit
def test_validate_match_warnings_event_scope_still_works(app, test_db, tournament, seeded_teams):
    """Standalone (event-scoped) tournaments still resolve through the registration_resolver."""
    with app.app_context():
        # `tournament` is a standalone (non-league) tournament; register two seeded teams
        # at the event scope so they count as registered.
        _register_team_for_event(tournament.url, "team_1")
        _register_team_for_event(tournament.url, "team_2")
        m = Match(
            name="M1",
            event=tournament.url,
            schedule_type=ScheduleType.STATIC,
            status=MatchStatus.NOT_STARTED,
            team1="team_1",
            team2="team_2",
        )
        db.session.add(m)
        db.session.flush()

        warnings = validate_match_warnings(tournament.url)
        unknown = [w for w in warnings if w["kind"] == "unknown_team"]
        assert unknown == []
