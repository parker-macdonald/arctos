"""
Tests for dynamic match scheduling (MatchGraph-based scheduler).

These tests validate recompute_all_match_times() / run_scheduling()
with the current Match/Tournament schema:
- Match.schedule_type (STATIC/SAFE/FAST/BREAK/JOIN)
- Match.previous_match for dependency chains
- Match.finalized_at for completion time used by the graph

The scheduler:
- Builds a dependency graph from previous_match and team1_initial/team2_initial refs
- Sets nominal_start_time from get_deps_latest_end_time() (uses finalized_at for end time)
- Respects STATIC matches as boundaries (not pulled forward)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.domain.enums import MatchStatus
from app.utils.scheduling import recompute_all_match_times
from models import Match, db


def _aware_utc(d: datetime) -> datetime:
    """Normalize possibly-naive datetimes to aware UTC for comparisons in tests."""
    if d is None:
        return None
    if d.tzinfo is None:
        return d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def _link_chain(matches: list) -> None:
    """Set previous_match so matches form a chain in order."""
    for i in range(1, len(matches)):
        matches[i].previous_match = matches[i - 1].uuid
        matches[i - 1].next_match = matches[i].uuid


class TestDynamicScheduling:
    @pytest.mark.unit
    def test_basic_dynamic_scheduling(self, app, test_db, tournament):
        """Completing a match updates subsequent dynamic matches' nominal times from dependency end."""
        tournament_url = tournament.url
        with app.app_context():
            base_time = datetime.now(timezone.utc)
            field = "Field 1"

            match1 = Match(
                name="Match 1",
                event=tournament_url,
                field=field,
                nominal_start_time=base_time.replace(tzinfo=None),
                schedule_type="SAFE",
                nominal_length=60,
                status=MatchStatus.COMPLETED,
            )
            match2 = Match(
                name="Match 2",
                event=tournament_url,
                field=field,
                nominal_start_time=(base_time + timedelta(hours=1)).replace(tzinfo=None),
                schedule_type="SAFE",
                nominal_length=60,
                status="NOT_STARTED",
            )
            match3 = Match(
                name="Match 3",
                event=tournament_url,
                field=field,
                nominal_start_time=(base_time + timedelta(hours=2)).replace(tzinfo=None),
                schedule_type="SAFE",
                nominal_length=60,
                status="NOT_STARTED",
            )
            db.session.add_all([match1, match2, match3])
            db.session.flush()
            _link_chain([match1, match2, match3])

            finalize_time = base_time + timedelta(minutes=55)
            match1.finalized_at = finalize_time.replace(tzinfo=None)
            db.session.commit()

            recompute_all_match_times(tournament_url)

            db.session.refresh(match2)
            db.session.refresh(match3)

            assert abs((_aware_utc(match2.nominal_start_time) - finalize_time).total_seconds()) < 2
            expected_match3 = finalize_time + timedelta(minutes=match2.nominal_length or 60)
            assert abs((_aware_utc(match3.nominal_start_time) - expected_match3).total_seconds()) < 2

    @pytest.mark.unit
    def test_static_match_boundary(self, app, test_db, tournament):
        """Dynamic scheduling does not change STATIC match times (boundary)."""
        tournament_url = tournament.url
        with app.app_context():
            base_time = datetime.now(timezone.utc)
            field = "Field 1"

            match1 = Match(
                name="Match 1",
                event=tournament_url,
                field=field,
                nominal_start_time=base_time.replace(tzinfo=None),
                schedule_type="SAFE",
                nominal_length=60,
                status=MatchStatus.COMPLETED,
            )
            match2 = Match(
                name="Match 2",
                event=tournament_url,
                field=field,
                nominal_start_time=(base_time + timedelta(hours=2)).replace(tzinfo=None),
                schedule_type="SAFE",
                nominal_length=60,
                status="NOT_STARTED",
            )
            boundary_static = Match(
                name="Match 3 Static",
                event=tournament_url,
                field=field,
                nominal_start_time=(base_time + timedelta(hours=4)).replace(tzinfo=None),
                schedule_type="STATIC",
                nominal_length=60,
                status=MatchStatus.TIME_FINALIZED,
            )
            after_boundary = Match(
                name="Match 4",
                event=tournament_url,
                field=field,
                nominal_start_time=(base_time + timedelta(hours=6)).replace(tzinfo=None),
                schedule_type="SAFE",
                nominal_length=60,
                status="NOT_STARTED",
            )
            db.session.add_all([match1, match2, boundary_static, after_boundary])
            db.session.flush()
            _link_chain([match1, match2, boundary_static, after_boundary])

            finalize_time = base_time + timedelta(minutes=50)
            match1.finalized_at = finalize_time.replace(tzinfo=None)
            db.session.commit()

            recompute_all_match_times(tournament_url)

            db.session.refresh(match2)
            db.session.refresh(boundary_static)
            db.session.refresh(after_boundary)

            assert abs((_aware_utc(match2.nominal_start_time) - finalize_time).total_seconds()) < 2
            assert (
                abs((_aware_utc(boundary_static.nominal_start_time) - (base_time + timedelta(hours=4))).total_seconds())
                < 2
            )
            assert (
                abs((_aware_utc(after_boundary.nominal_start_time) - (base_time + timedelta(hours=5))).total_seconds())
                < 2
            )

    @pytest.mark.unit
    def test_dependency_constraint_same_field(self, app, test_db, tournament):
        """A match cannot be scheduled earlier than its dependency's completion time."""
        tournament_url = tournament.url
        with app.app_context():
            base_time = datetime.now(timezone.utc)
            field = "Field 1"

            completed = Match(
                name="Trigger",
                event=tournament_url,
                field=field,
                nominal_start_time=base_time.replace(tzinfo=None),
                schedule_type="SAFE",
                nominal_length=60,
                status=MatchStatus.COMPLETED,
            )
            dep = Match(
                name="Dep",
                event=tournament_url,
                field=field,
                nominal_start_time=(base_time + timedelta(hours=1, minutes=30)).replace(tzinfo=None),
                schedule_type="SAFE",
                nominal_length=60,
                status=MatchStatus.COMPLETED,
            )
            next_match = Match(
                name="Next",
                event=tournament_url,
                field=field,
                nominal_start_time=(base_time + timedelta(hours=1)).replace(tzinfo=None),
                schedule_type="SAFE",
                nominal_length=60,
                status="NOT_STARTED",
            )
            constrained = Match(
                name="Constrained",
                event=tournament_url,
                field=field,
                nominal_start_time=(base_time + timedelta(hours=2)).replace(tzinfo=None),
                schedule_type="SAFE",
                nominal_length=60,
                team1_initial="Dep::winner",
                status="NOT_STARTED",
            )
            db.session.add_all([completed, dep, next_match, constrained])
            db.session.flush()
            next_match.previous_match = completed.uuid
            constrained.previous_match = next_match.uuid
            # Constrained also depends on Dep via team1_initial

            dep_late = base_time + timedelta(hours=3)
            completed.finalized_at = base_time + timedelta(minutes=50)
            dep.finalized_at = dep_late.replace(tzinfo=None)
            db.session.commit()

            recompute_all_match_times(tournament_url)

            db.session.refresh(next_match)
            db.session.refresh(constrained)

            assert (
                abs((_aware_utc(next_match.nominal_start_time) - (base_time + timedelta(minutes=50))).total_seconds())
                < 2
            )
            assert _aware_utc(constrained.nominal_start_time) >= _aware_utc(dep_late)

    @pytest.mark.unit
    def test_dependency_on_different_field_does_not_constrain(self, app, test_db, tournament):
        """Completing a match on one field does not change times on another field."""
        tournament_url = tournament.url
        with app.app_context():
            base_time = datetime.now(timezone.utc)

            completed = Match(
                name="Field1 Trigger",
                event=tournament_url,
                field="Field 1",
                nominal_start_time=base_time.replace(tzinfo=None),
                schedule_type="SAFE",
                nominal_length=60,
                status=MatchStatus.COMPLETED,
            )
            other_field_dep = Match(
                name="Dep",
                event=tournament_url,
                field="Field 2",
                nominal_start_time=(base_time + timedelta(hours=1)).replace(tzinfo=None),
                schedule_type="SAFE",
                nominal_length=60,
                status=MatchStatus.COMPLETED,
            )
            other_field_match = Match(
                name="Field2 Match",
                event=tournament_url,
                field="Field 2",
                nominal_start_time=(base_time + timedelta(hours=2)).replace(tzinfo=None),
                schedule_type="SAFE",
                nominal_length=60,
                team1_initial="Dep::winner",
                status="NOT_STARTED",
            )
            db.session.add_all([completed, other_field_dep, other_field_match])
            db.session.flush()
            other_field_match.previous_match = other_field_dep.uuid

            completed.finalized_at = base_time + timedelta(minutes=50)
            db.session.commit()

            original = _aware_utc(other_field_match.nominal_start_time)
            recompute_all_match_times(tournament_url)

            db.session.refresh(other_field_match)
            assert _aware_utc(other_field_match.nominal_start_time) == original

    @pytest.mark.unit
    def test_multiple_dependencies_latest_wins(self, app, test_db, tournament):
        """When a match has multiple completed dependencies, latest completion time wins."""
        tournament_url = tournament.url
        with app.app_context():
            base_time = datetime.now(timezone.utc)
            field = "Field 1"

            trigger = Match(
                name="Trigger",
                event=tournament_url,
                field=field,
                nominal_start_time=base_time.replace(tzinfo=None),
                schedule_type="SAFE",
                nominal_length=60,
                status=MatchStatus.COMPLETED,
            )
            dep1 = Match(
                name="Dep 1",
                event=tournament_url,
                field=field,
                nominal_start_time=(base_time + timedelta(hours=1)).replace(tzinfo=None),
                schedule_type="SAFE",
                nominal_length=60,
                status=MatchStatus.COMPLETED,
            )
            dep2 = Match(
                name="Dep 2",
                event=tournament_url,
                field=field,
                nominal_start_time=(base_time + timedelta(hours=1, minutes=10)).replace(tzinfo=None),
                schedule_type="SAFE",
                nominal_length=60,
                status=MatchStatus.COMPLETED,
            )
            next_match = Match(
                name="Next",
                event=tournament_url,
                field=field,
                nominal_start_time=(base_time + timedelta(hours=2)).replace(tzinfo=None),
                schedule_type="SAFE",
                nominal_length=60,
                status="NOT_STARTED",
            )
            target = Match(
                name="Target",
                event=tournament_url,
                field=field,
                nominal_start_time=(base_time + timedelta(hours=3)).replace(tzinfo=None),
                schedule_type="SAFE",
                nominal_length=60,
                team1_initial="Dep 1::winner",
                team2_initial="Dep 2::winner",
                status="NOT_STARTED",
            )
            db.session.add_all([trigger, dep1, dep2, next_match, target])
            db.session.flush()
            next_match.previous_match = trigger.uuid
            target.previous_match = next_match.uuid

            trigger.finalized_at = base_time + timedelta(minutes=50)
            dep1.finalized_at = (base_time + timedelta(hours=2)).replace(tzinfo=None)
            dep2.finalized_at = (base_time + timedelta(hours=4)).replace(tzinfo=None)
            db.session.commit()

            recompute_all_match_times(tournament_url)

            db.session.refresh(target)
            assert _aware_utc(target.nominal_start_time) >= _aware_utc(dep2.finalized_at)

    @pytest.mark.unit
    def test_no_subsequent_matches(self, app, test_db, tournament):
        """Completing the last match on a field should not error."""
        tournament_url = tournament.url
        with app.app_context():
            base_time = datetime.now(timezone.utc)
            field = "Field 1"

            match1 = Match(
                name="Only Match",
                event=tournament_url,
                field=field,
                nominal_start_time=base_time.replace(tzinfo=None),
                schedule_type="SAFE",
                nominal_length=60,
                status=MatchStatus.COMPLETED,
            )
            db.session.add(match1)
            db.session.commit()

            recompute_all_match_times(tournament_url)

    @pytest.mark.unit
    def test_match_without_field(self, app, test_db, tournament):
        """Matches without a field can be processed without errors."""
        tournament_url = tournament.url
        with app.app_context():
            base_time = datetime.now(timezone.utc)

            match1 = Match(
                name="No Field",
                event=tournament_url,
                field=None,
                nominal_start_time=base_time.replace(tzinfo=None),
                schedule_type="SAFE",
                nominal_length=60,
                status=MatchStatus.COMPLETED,
            )
            db.session.add(match1)
            db.session.commit()

            recompute_all_match_times(tournament_url)
