"""
Tests for dynamic match scheduling functionality.

These tests validate `update_dynamic_schedule_after_completion()` against the
current Match/Tournament schema:
- Match.schedule_type (STATIC/DYNAMIC/BREAK/JOIN), not a boolean `dynamic`
- Match.completed_time for "finished at", not a JSON `gamestate`

The scheduling update function:
- pulls forward subsequent non-STATIC matches on the same field
- stops at the first STATIC match (boundary)
- constrains later matches by dependency completion times when those dependencies
  are resolvable on the same field (for non-JOIN matches)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.utils.scheduling import update_dynamic_schedule_after_completion
from models import Match, db


def _aware_utc(d: datetime) -> datetime:
    """Normalize possibly-naive datetimes to aware UTC for comparisons in tests."""
    if d.tzinfo is None:
        return d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


class TestDynamicScheduling:
    @pytest.mark.unit
    def test_basic_dynamic_scheduling(self, app, test_db, tournament):
        """Completing a match pulls forward subsequent dynamic matches on the same field."""
        tournament_url = tournament.url
        with app.app_context():
            base_time = datetime.now(timezone.utc)
            field = "Field 1"
            
            match1 = Match(
                name="Match 1",
                event=tournament_url,
                field=field,
                nominal_start_time=base_time.replace(tzinfo=None),
                schedule_type="DYNAMIC",
                nominal_length=60,
                status="COMPLETED",
                completed_time=base_time + timedelta(minutes=60),
            )
            
            match2 = Match(
                name="Match 2",
                event=tournament_url,
                field=field,
                nominal_start_time=(base_time + timedelta(hours=1)).replace(tzinfo=None),
                schedule_type="DYNAMIC",
                nominal_length=60,
                status="NOT_STARTED",
            )
            
            match3 = Match(
                name="Match 3",
                event=tournament_url,
                field=field,
                nominal_start_time=(base_time + timedelta(hours=2)).replace(tzinfo=None),
                schedule_type="DYNAMIC",
                nominal_length=60,
                status="NOT_STARTED",
            )
            
            db.session.add_all([match1, match2, match3])
            db.session.commit()
            
            finalize_time = base_time + timedelta(minutes=55)  # finished 5 minutes early
            match1.completed_time = finalize_time
            db.session.commit()
            
            update_dynamic_schedule_after_completion(tournament_url, match1)
            
            db.session.refresh(match2)
            db.session.refresh(match3)
            
            # Match2 pulled to match1 completion (stored as naive)
            assert abs((_aware_utc(match2.nominal_start_time) - finalize_time).total_seconds()) < 2
            
            # Match3 scheduled back-to-back after match2
            expected_match3 = finalize_time + timedelta(minutes=match2.nominal_length or 60)
            assert abs((_aware_utc(match3.nominal_start_time) - expected_match3).total_seconds()) < 2
    
    @pytest.mark.unit
    def test_static_match_boundary(self, app, test_db, tournament):
        """Dynamic scheduling stops at the next STATIC match (boundary)."""
        tournament_url = tournament.url
        with app.app_context():
            base_time = datetime.now(timezone.utc)
            field = "Field 1"
            
            match1 = Match(
                name="Match 1",
                event=tournament_url,
                field=field,
                nominal_start_time=base_time.replace(tzinfo=None),
                schedule_type="DYNAMIC",
                nominal_length=60,
                status="COMPLETED",
                completed_time=base_time + timedelta(minutes=60),
            )
            
            match2 = Match(
                name="Match 2",
                event=tournament_url,
                field=field,
                nominal_start_time=(base_time + timedelta(hours=2)).replace(tzinfo=None),
                schedule_type="DYNAMIC",
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
                status="NOT_STARTED",
            )
            
            after_boundary = Match(
                name="Match 4",
                event=tournament_url,
                field=field,
                nominal_start_time=(base_time + timedelta(hours=6)).replace(tzinfo=None),
                schedule_type="DYNAMIC",
                nominal_length=60,
                status="NOT_STARTED",
            )
            
            db.session.add_all([match1, match2, boundary_static, after_boundary])
            db.session.commit()
            
            finalize_time = base_time + timedelta(minutes=50)
            match1.completed_time = finalize_time
            db.session.commit()
            
            update_dynamic_schedule_after_completion(tournament_url, match1)
            
            db.session.refresh(match2)
            db.session.refresh(boundary_static)
            db.session.refresh(after_boundary)

            assert abs((_aware_utc(match2.nominal_start_time) - finalize_time).total_seconds()) < 2

            # Boundary/static is not touched by this function
            assert abs((_aware_utc(boundary_static.nominal_start_time) - (base_time + timedelta(hours=4))).total_seconds()) < 2

            # After boundary is not touched
            assert abs((_aware_utc(after_boundary.nominal_start_time) - (base_time + timedelta(hours=6))).total_seconds()) < 2
    
    @pytest.mark.unit
    def test_dependency_constraint_same_field(self, app, test_db, tournament):
        """A later match in the chain cannot be pulled earlier than its dependency completion time."""
        tournament_url = tournament.url
        with app.app_context():
            base_time = datetime.now(timezone.utc)
            field = "Field 1"

            completed = Match(
                name="Trigger",
                event=tournament_url,
                field=field,
                nominal_start_time=base_time.replace(tzinfo=None),
                schedule_type="DYNAMIC",
                nominal_length=60,
                status="COMPLETED",
                completed_time=base_time + timedelta(minutes=60),
            )

            # A dependency match on the same field that finishes late
            dep = Match(
                name="Dep",
                event=tournament_url,
                field=field,
                nominal_start_time=(base_time + timedelta(hours=1, minutes=30)).replace(tzinfo=None),
                schedule_type="DYNAMIC",
                nominal_length=60,
                status="COMPLETED",
                completed_time=base_time + timedelta(hours=3),  # very late completion
            )

            next_match = Match(
                name="Next",
                event=tournament_url,
                field=field,
                nominal_start_time=(base_time + timedelta(hours=1)).replace(tzinfo=None),
                schedule_type="DYNAMIC",
                nominal_length=60,
                status="NOT_STARTED",
            )
            
            constrained = Match(
                name="Constrained",
                event=tournament_url,
                field=field,
                nominal_start_time=(base_time + timedelta(hours=2)).replace(tzinfo=None),
                schedule_type="DYNAMIC",
                nominal_length=60,
                team1_initial="Dep winner",
                status="NOT_STARTED",
            )
            
            db.session.add_all([completed, dep, next_match, constrained])
            db.session.commit()
            
            # Complete the trigger early
            finalize_time = base_time + timedelta(minutes=50)
            completed.completed_time = finalize_time
            db.session.commit()
            
            update_dynamic_schedule_after_completion(tournament_url, completed)
            
            db.session.refresh(next_match)
            db.session.refresh(constrained)
            
            # Next match is pulled to finalize_time
            assert abs((_aware_utc(next_match.nominal_start_time) - finalize_time).total_seconds()) < 2

            # Constrained match cannot be earlier than dep.completed_time (3h)
            assert _aware_utc(constrained.nominal_start_time) >= _aware_utc(dep.completed_time)
    
    @pytest.mark.unit
    def test_dependency_on_different_field_does_not_constrain(self, app, test_db, tournament):
        """Non-JOIN dependencies on other fields do not constrain field-local pull-forward logic."""
        tournament_url = tournament.url
        with app.app_context():
            base_time = datetime.now(timezone.utc)
            
            completed = Match(
                name="Field1 Trigger",
                event=tournament_url,
                field="Field 1",
                nominal_start_time=base_time.replace(tzinfo=None),
                schedule_type="DYNAMIC",
                nominal_length=60,
                status="COMPLETED",
                completed_time=base_time + timedelta(minutes=45),
            )
            
            other_field_dep = Match(
                name="Dep",
                event=tournament_url,
                field="Field 2",
                nominal_start_time=(base_time + timedelta(hours=1)).replace(tzinfo=None),
                schedule_type="DYNAMIC",
                nominal_length=60,
                status="COMPLETED",
                completed_time=base_time + timedelta(hours=3),
            )

            other_field_match = Match(
                name="Field2 Match",
                event=tournament_url,
                field="Field 2",
                nominal_start_time=(base_time + timedelta(hours=2)).replace(tzinfo=None),
                schedule_type="DYNAMIC",
                nominal_length=60,
                team1_initial="Dep winner",
                status="NOT_STARTED",
            )

            db.session.add_all([completed, other_field_dep, other_field_match])
            db.session.commit()
            
            original = _aware_utc(other_field_match.nominal_start_time)
            update_dynamic_schedule_after_completion(tournament_url, completed)
            
            db.session.refresh(other_field_match)
            assert _aware_utc(other_field_match.nominal_start_time) == original
    
    @pytest.mark.unit
    def test_multiple_dependencies_latest_wins(self, app, test_db, tournament):
        """If a match references multiple completed dependencies, the latest completion time wins."""
        tournament_url = tournament.url
        with app.app_context():
            base_time = datetime.now(timezone.utc)
            field = "Field 1"

            trigger = Match(
                name="Trigger",
                event=tournament_url,
                field=field,
                nominal_start_time=base_time.replace(tzinfo=None),
                schedule_type="DYNAMIC",
                nominal_length=60,
                status="COMPLETED",
                completed_time=base_time + timedelta(minutes=60),
            )

            dep1 = Match(
                name="Dep 1",
                event=tournament_url,
                field=field,
                nominal_start_time=(base_time + timedelta(hours=1)).replace(tzinfo=None),
                schedule_type="DYNAMIC",
                nominal_length=60,
                status="COMPLETED",
                completed_time=base_time + timedelta(hours=2),
            )
            
            dep2 = Match(
                name="Dep 2",
                event=tournament_url,
                field=field,
                nominal_start_time=(base_time + timedelta(hours=1, minutes=10)).replace(tzinfo=None),
                schedule_type="DYNAMIC",
                nominal_length=60,
                status="COMPLETED",
                completed_time=base_time + timedelta(hours=4),
            )
            
            next_match = Match(
                name="Next",
                event=tournament_url,
                field=field,
                nominal_start_time=(base_time + timedelta(hours=2)).replace(tzinfo=None),
                schedule_type="DYNAMIC",
                nominal_length=60,
                status="NOT_STARTED",
            )

            target = Match(
                name="Target",
                event=tournament_url,
                field=field,
                nominal_start_time=(base_time + timedelta(hours=3)).replace(tzinfo=None),
                schedule_type="DYNAMIC",
                nominal_length=60,
                team1_initial="Dep 1 winner",
                team2_initial="Dep 2 winner",
                status="NOT_STARTED",
            )
            
            db.session.add_all([trigger, dep1, dep2, next_match, target])
            db.session.commit()
            
            trigger.completed_time = base_time + timedelta(minutes=50)
            db.session.commit()
            
            update_dynamic_schedule_after_completion(tournament_url, trigger)
            
            db.session.refresh(target)
            assert _aware_utc(target.nominal_start_time) >= _aware_utc(dep2.completed_time)
    
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
                schedule_type="DYNAMIC",
                nominal_length=60,
                status="COMPLETED",
                completed_time=base_time + timedelta(minutes=60),
            )
            db.session.add(match1)
            db.session.commit()
            
            update_dynamic_schedule_after_completion(tournament_url, match1)
    
    @pytest.mark.unit
    def test_match_without_field(self, app, test_db, tournament):
        """Matches without a field return early without errors."""
        tournament_url = tournament.url
        with app.app_context():
            base_time = datetime.now(timezone.utc)
            
            match1 = Match(
                name="No Field",
                event=tournament_url,
                field=None,
                nominal_start_time=base_time.replace(tzinfo=None),
                schedule_type="DYNAMIC",
                nominal_length=60,
                status="COMPLETED",
                completed_time=base_time + timedelta(minutes=60),
            )
            db.session.add(match1)
            db.session.commit()
            
            update_dynamic_schedule_after_completion(tournament_url, match1)
    
    @pytest.mark.unit
    def test_unresolved_dependency_preserves_time(self, app, test_db, tournament):
        """If a dependency exists but has no completion timestamp, do not pull earlier than existing time."""
        tournament_url = tournament.url
        with app.app_context():
            base_time = datetime.now(timezone.utc)
            field = "Field 1"

            trigger = Match(
                name="Trigger",
                event=tournament_url,
                field=field,
                nominal_start_time=base_time.replace(tzinfo=None),
                schedule_type="DYNAMIC",
                nominal_length=60,
                status="COMPLETED",
                completed_time=base_time + timedelta(minutes=50),
            )

            next_match = Match(
                name="Next",
                event=tournament_url,
                field=field,
                nominal_start_time=(base_time + timedelta(hours=1)).replace(tzinfo=None),
                schedule_type="DYNAMIC",
                nominal_length=60,
                status="NOT_STARTED",
            )
            
            # Exists, but is not completed (no completed_time)
            dep = Match(
                name="Dep",
                event=tournament_url,
                field=field,
                nominal_start_time=(base_time + timedelta(hours=2)).replace(tzinfo=None),
                schedule_type="DYNAMIC",
                nominal_length=60,
                status="NOT_STARTED",
            )
            
            # This match references Dep, but Dep has no completed_time => deps_ready_at None.
            # The algorithm must not pull this earlier than its existing nominal time.
            target = Match(
                name="Target",
                event=tournament_url,
                field=field,
                nominal_start_time=(base_time + timedelta(hours=5)).replace(tzinfo=None),
                schedule_type="DYNAMIC",
                nominal_length=60,
                team1_initial="Dep winner",
                status="NOT_STARTED",
            )
            
            db.session.add_all([trigger, next_match, dep, target])
            db.session.commit()
            
            original_target = _aware_utc(target.nominal_start_time)
            update_dynamic_schedule_after_completion(tournament_url, trigger)

            db.session.refresh(target)
            assert _aware_utc(target.nominal_start_time) == original_target


