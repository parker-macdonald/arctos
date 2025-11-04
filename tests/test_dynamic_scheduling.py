"""
Tests for dynamic match scheduling functionality.

Tests that when a match is completed, subsequent dynamic matches on the same field
are pulled forward appropriately, respecting dependency constraints.
"""
import pytest
import json
from datetime import datetime, timedelta, timezone
from app.utils.scheduling import update_dynamic_schedule_after_completion
from models import Match, db


class TestDynamicScheduling:
    """Test suite for dynamic match scheduling."""
    
    @pytest.mark.unit
    def test_basic_dynamic_scheduling(self, test_db, tournament):
        """Test basic case: match completion pulls forward subsequent dynamic matches."""
        from tests.conftest import app
        # Extract tournament URL before entering app context to avoid DetachedInstanceError
        tournament_url = tournament.url
        with app.app_context():
            # Merge tournament into current session for any queries that need it
            tournament_merged = db.session.merge(tournament)
            base_time = datetime.now(timezone.utc)
            field = 'Field 1'
            
            # Create matches on the same field
            match1 = Match(
                name='Match 1',
                event=tournament_url,
                field=field,
                nominal_start_time=base_time,
                dynamic=False,
                nominal_length=60,
                status='COMPLETED',
                gamestate=json.dumps({'finalized_at': base_time.isoformat(), 'match_winner': 'TEAM1'})
            )
            
            match2 = Match(
                name='Match 2',
                event=tournament_url,
                field=field,
                nominal_start_time=base_time + timedelta(hours=1),
                dynamic=True,
                nominal_length=60,
                status='NOT_STARTED'
            )
            
            match3 = Match(
                name='Match 3',
                event=tournament_url,
                field=field,
                nominal_start_time=base_time + timedelta(hours=2),
                dynamic=True,
                nominal_length=60,
                status='NOT_STARTED'
            )
            
            db.session.add_all([match1, match2, match3])
            db.session.commit()
            
            # Finalize match1 - this should trigger scheduling update
            finalize_time = base_time + timedelta(minutes=55)  # Match finished 5 minutes early
            match1.gamestate = json.dumps({
                'finalized_at': finalize_time.isoformat(),
                'match_winner': 'TEAM1'
            })
            db.session.commit()
            
            # Call the scheduling update function
            update_dynamic_schedule_after_completion(tournament_url, match1)
            
            # Refresh from database
            db.session.refresh(match2)
            db.session.refresh(match3)
            
            # Match2 should be marked ready_to_start but nominal time unchanged
            match2_gamestate = json.loads(match2.gamestate) if match2.gamestate else {}
            assert match2_gamestate.get('ready_to_start') is True
            # Normalize timezone for comparison (database may return naive datetimes)
            match2_time = match2.nominal_start_time.replace(tzinfo=timezone.utc) if match2.nominal_start_time.tzinfo is None else match2.nominal_start_time
            assert match2_time == base_time + timedelta(hours=1)
            
            # Match3 should have confirmed_start_time set to back-to-back after match2
            expected_start = finalize_time + timedelta(minutes=60)  # match2 nominal_length
            assert match3.confirmed_start_time is not None
            # Normalize timezone for comparison (database may return naive datetimes)
            match3_confirmed = match3.confirmed_start_time.replace(tzinfo=timezone.utc) if match3.confirmed_start_time.tzinfo is None else match3.confirmed_start_time
            # Allow 1 second tolerance for timing
            assert abs((match3_confirmed - expected_start).total_seconds()) < 2
    
    @pytest.mark.unit
    def test_static_match_boundary(self, test_db, tournament):
        """Test that dynamic scheduling stops at static matches."""
        from tests.conftest import app
        tournament_url = tournament.url
        with app.app_context():
            base_time = datetime.now(timezone.utc)
            field = 'Field 1'
            
            match1 = Match(
                name='Match 1',
                event=tournament_url,
                field=field,
                nominal_start_time=base_time,
                dynamic=True,
                nominal_length=60,
                status='COMPLETED',
                gamestate=json.dumps({'finalized_at': base_time.isoformat(), 'match_winner': 'TEAM1'})
            )
            
            match2 = Match(
                name='Match 2',
                event=tournament_url,
                field=field,
                nominal_start_time=base_time + timedelta(hours=2),
                dynamic=True,
                nominal_length=60,
                status='NOT_STARTED'
            )
            
            match3_static = Match(
                name='Match 3 Static',
                event=tournament_url,
                field=field,
                nominal_start_time=base_time + timedelta(hours=4),
                dynamic=False,  # Static match
                nominal_length=60,
                status='NOT_STARTED'
            )
            
            match4 = Match(
                name='Match 4',
                event=tournament_url,
                field=field,
                nominal_start_time=base_time + timedelta(hours=6),
                dynamic=True,
                nominal_length=60,
                status='NOT_STARTED'
            )
            
            db.session.add_all([match1, match2, match3_static, match4])
            db.session.commit()
            
            finalize_time = base_time + timedelta(minutes=50)
            match1.gamestate = json.dumps({
                'finalized_at': finalize_time.isoformat(),
                'match_winner': 'TEAM1'
            })
            db.session.commit()
            
            update_dynamic_schedule_after_completion(tournament_url, match1)
            
            db.session.refresh(match2)
            db.session.refresh(match3_static)
            db.session.refresh(match4)
            
            # Match2 should be updated (ready_to_start)
            match2_gamestate = json.loads(match2.gamestate) if match2.gamestate else {}
            assert match2_gamestate.get('ready_to_start') is True
            
            # Match3_static should NOT be modified (boundary)
            if match3_static.confirmed_start_time is not None:
                # Normalize timezone for comparison
                confirmed = match3_static.confirmed_start_time.replace(tzinfo=timezone.utc) if match3_static.confirmed_start_time.tzinfo is None else match3_static.confirmed_start_time
                nominal = match3_static.nominal_start_time.replace(tzinfo=timezone.utc) if match3_static.nominal_start_time.tzinfo is None else match3_static.nominal_start_time
                assert confirmed == nominal
            else:
                assert match3_static.confirmed_start_time is None
            
            # Match4 should NOT be modified (after static boundary)
            assert match4.confirmed_start_time is None
    
    @pytest.mark.unit
    def test_dependency_constraint(self, test_db, tournament):
        """Test that matches are only pulled forward as far as their dependencies allow."""
        from tests.conftest import app
        tournament_url = tournament.url

        with app.app_context():
            base_time = datetime.now(timezone.utc)
            field = 'Field 1'
            
            # Match 1 - will be completed first
            match1 = Match(
                name='Match 1',
                event=tournament_url,
                field=field,
                nominal_start_time=base_time,
                dynamic=True,
                nominal_length=30,  # Short match
                status='COMPLETED',
                gamestate=json.dumps({
                    'finalized_at': (base_time + timedelta(minutes=25)).isoformat(),
                    'match_winner': 'TEAM1'
                })
            )
            
            # Match 2 - depends on Match 1 winner
            match2 = Match(
                name='Match 2',
                event=tournament_url,
                field=field,
                nominal_start_time=base_time + timedelta(hours=1),
                dynamic=True,
                nominal_length=60,
                team1_initial='Match 1 winner',  # Dependency!
                status='NOT_STARTED'
            )
            
            # Match 3 - no dependencies, should be pulled forward immediately
            match3 = Match(
                name='Match 3',
                event=tournament_url,
                field=field,
                nominal_start_time=base_time + timedelta(hours=3),
                dynamic=True,
                nominal_length=60,
                status='NOT_STARTED'
            )
            
            db.session.add_all([match1, match2, match3])
            db.session.commit()
            
            # Update match1's finalized time to be earlier
            early_finalize = base_time + timedelta(minutes=20)
            match1.gamestate = json.dumps({
                'finalized_at': early_finalize.isoformat(),
                'match_winner': 'TEAM1'
            })
            db.session.commit()
            
            update_dynamic_schedule_after_completion(tournament_url, match1)
            
            db.session.refresh(match2)
            db.session.refresh(match3)
            
            # Match2 depends on match1, which was finalized at early_finalize
            # So match2 should be constrained to start no earlier than early_finalize
            # But also should respect back-to-back scheduling
            
            # Match2 should have ready_to_start flag
            match2_gamestate = json.loads(match2.gamestate) if match2.gamestate else {}
            assert match2_gamestate.get('ready_to_start') is True
            
            # Match3 should be scheduled back-to-back after match2
            assert match3.confirmed_start_time is not None
    
    @pytest.mark.unit
    def test_dependency_on_different_field(self, test_db, tournament):
        """Test that dependencies on matches from different fields are found correctly."""
        from tests.conftest import app
        tournament_url = tournament.url

        with app.app_context():
            base_time = datetime.now(timezone.utc)
            
            # Match on Field 1 that will complete
            match1 = Match(
                name='Match 1',
                event=tournament_url,
                field='Field 1',
                nominal_start_time=base_time,
                dynamic=True,
                nominal_length=60,
                status='COMPLETED',
                gamestate=json.dumps({
                    'finalized_at': (base_time + timedelta(minutes=50)).isoformat(),
                    'match_winner': 'TEAM1'
                })
            )
            
            # Match on Field 2 that depends on Match 1
            match2 = Match(
                name='Match 2',
                event=tournament_url,
                field='Field 2',
                nominal_start_time=base_time + timedelta(hours=2),
                dynamic=True,
                nominal_length=60,
                team1_initial='Match 1 winner',
                status='NOT_STARTED'
            )
            
            db.session.add_all([match1, match2])
            db.session.commit()
            
            # Complete match1
            finalize_time = base_time + timedelta(minutes=45)
            match1.gamestate = json.dumps({
                'finalized_at': finalize_time.isoformat(),
                'match_winner': 'TEAM1'
            })
            db.session.commit()
            
            # This should NOT affect match2 since it's on a different field
            update_dynamic_schedule_after_completion(tournament_url, match1)
            
            db.session.refresh(match2)
            assert match2.confirmed_start_time is None
            match2_gamestate = json.loads(match2.gamestate) if match2.gamestate else {}
            assert match2_gamestate.get('ready_to_start') is None
    
    @pytest.mark.unit
    def test_multiple_dependencies_latest_wins(self, test_db, tournament):
        """Test that when a match has multiple dependencies, the latest completion time is used."""
        from tests.conftest import app
        tournament_url = tournament.url
        with app.app_context():
            base_time = datetime.now(timezone.utc)
            field = 'Field 1'
            
            # Match 1 - completes early
            match1 = Match(
                name='Match 1',
                event=tournament_url,
                field=field,
                nominal_start_time=base_time,
                dynamic=True,
                nominal_length=60,
                status='COMPLETED',
                gamestate=json.dumps({
                    'finalized_at': (base_time + timedelta(minutes=50)).isoformat(),
                    'match_winner': 'TEAM1'
                })
            )
            
            # Match 2 - depends on match1, completes later
            match2 = Match(
                name='Match 2',
                event=tournament_url,
                field=field,
                nominal_start_time=base_time + timedelta(hours=2),
                dynamic=True,
                nominal_length=60,
                team1_initial='Match 1 winner',
                status='NOT_STARTED'
            )
            
            # Match 3 - depends on both match1 and match2
            match3 = Match(
                name='Match 3',
                event=tournament_url,
                field=field,
                nominal_start_time=base_time + timedelta(hours=4),
                dynamic=True,
                nominal_length=60,
                team1_initial='Match 1 winner',
                team2_initial='Match 2 winner',
                status='NOT_STARTED'
            )
            
            db.session.add_all([match1, match2, match3])
            db.session.commit()
            
            # Complete match1
            match1_finalize = base_time + timedelta(minutes=45)
            match1.gamestate = json.dumps({
                'finalized_at': match1_finalize.isoformat(),
                'match_winner': 'TEAM1'
            })
            db.session.commit()
            
            update_dynamic_schedule_after_completion(tournament_url, match1)
            
            # Now complete match2 later
            match2_finalize = base_time + timedelta(hours=3, minutes=30)
            match2.status = 'COMPLETED'
            match2.gamestate = json.dumps({
                'finalized_at': match2_finalize.isoformat(),
                'match_winner': 'TEAM2'
            })
            db.session.commit()
            
            update_dynamic_schedule_after_completion(tournament_url, match2)
            
            db.session.refresh(match3)
            
            # Match3 should be constrained by match2's later completion time
            assert match3.confirmed_start_time is not None
            # Normalize timezone for comparison (database may return naive datetimes)
            match3_confirmed = match3.confirmed_start_time.replace(tzinfo=timezone.utc) if match3.confirmed_start_time.tzinfo is None else match3.confirmed_start_time
            # Should be at least as late as match2's finalization
            assert match3_confirmed >= match2_finalize
    
    @pytest.mark.unit
    def test_no_subsequent_matches(self, test_db, tournament):
        """Test that completing the last match on a field doesn't cause errors."""
        from tests.conftest import app
        tournament_url = tournament.url
        with app.app_context():
            base_time = datetime.now(timezone.utc)
            field = 'Field 1'
            
            match1 = Match(
                name='Match 1',
                event=tournament_url,
                field=field,
                nominal_start_time=base_time,
                dynamic=True,
                nominal_length=60,
                status='COMPLETED',
                gamestate=json.dumps({
                    'finalized_at': base_time.isoformat(),
                    'match_winner': 'TEAM1'
                })
            )
            
            db.session.add(match1)
            db.session.commit()
            
            # Should not raise an error
            update_dynamic_schedule_after_completion(tournament_url, match1)
            
            # Should complete successfully
            assert True
    
    @pytest.mark.unit
    def test_match_without_field(self, test_db, tournament):
        """Test that matches without a field don't trigger scheduling updates."""
        from tests.conftest import app
        tournament_url = tournament.url
        with app.app_context():
            base_time = datetime.now(timezone.utc)
            
            match1 = Match(
                name='Match 1',
                event=tournament_url,
                field=None,  # No field
                nominal_start_time=base_time,
                dynamic=True,
                nominal_length=60,
                status='COMPLETED',
                gamestate=json.dumps({
                    'finalized_at': base_time.isoformat(),
                    'match_winner': 'TEAM1'
                })
            )
            
            db.session.add(match1)
            db.session.commit()
            
            # Should return early without errors
            update_dynamic_schedule_after_completion(tournament_url, match1)
            
            assert True
    
    @pytest.mark.unit
    def test_unresolved_dependency_preserves_time(self, test_db, tournament):
        """Test that matches with unresolved dependencies don't get pulled earlier."""
        from tests.conftest import app
        tournament_url = tournament.url
        with app.app_context():
            base_time = datetime.now(timezone.utc)
            field = 'Field 1'
            
            match1 = Match(
                name='Match 1',
                event=tournament_url,
                field=field,
                nominal_start_time=base_time,
                dynamic=True,
                nominal_length=60,
                status='COMPLETED',
                gamestate=json.dumps({
                    'finalized_at': (base_time + timedelta(minutes=50)).isoformat(),
                    'match_winner': 'TEAM1'
                })
            )
            
            # Match2 depends on a match that hasn't been completed yet
            match2 = Match(
                name='Match 2',
                event=tournament_url,
                field=field,
                nominal_start_time=base_time + timedelta(hours=3),
                dynamic=True,
                nominal_length=60,
                team1_initial='Nonexistent Match winner',  # Unresolved dependency
                status='NOT_STARTED'
            )
            
            match3 = Match(
                name='Match 3',
                event=tournament_url,
                field=field,
                nominal_start_time=base_time + timedelta(hours=5),
                dynamic=True,
                nominal_length=60,
                status='NOT_STARTED'
            )
            
            db.session.add_all([match1, match2, match3])
            db.session.commit()
            
            original_match2_time = match2.nominal_start_time
            original_match3_time = match3.nominal_start_time
            
            update_dynamic_schedule_after_completion(tournament_url, match1)
            
            db.session.refresh(match2)
            db.session.refresh(match3)
            
            # Match2 should not be moved earlier than its nominal time (unresolved dependency)
            if match2.confirmed_start_time:
                # Normalize timezone for comparison
                match2_confirmed = match2.confirmed_start_time.replace(tzinfo=timezone.utc) if match2.confirmed_start_time.tzinfo is None else match2.confirmed_start_time
                assert match2_confirmed >= original_match2_time
            else:
                # Normalize timezone for comparison
                match2_nominal = match2.nominal_start_time.replace(tzinfo=timezone.utc) if match2.nominal_start_time.tzinfo is None else match2.nominal_start_time
                assert match2_nominal == original_match2_time
            
            # Match3 should be updated normally (no dependencies)
            assert match3.confirmed_start_time is not None
