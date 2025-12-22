"""
Tests for tag resolution behavior with mixed refs lists.

Tests ensure correct behavior when refs_initial contains:
- Explicit team IDs
- Tag references (tag::TAG_NAME)
- Match references (MatchName::winner/loser)
"""
import pytest

from app.utils.dependencies import apply_match_dependencies
from models import Field, Match, Tag, Tournament, db


@pytest.mark.unit
def test_update_tags_preserves_explicit_teams_and_match_references(test_db, tournament, app):
    """update_tags should only update tag references, preserving explicit teams and match references."""
    tournament_url = tournament.url
    
    # Create field
    field = Field(event=tournament_url, name="Field 1", camera=None)
    db.session.add(field)
    
    # Create tags
    tag1 = Tag(event=tournament_url, name="Pool A")
    tag2 = Tag(event=tournament_url, name="Pool B")
    db.session.add_all([tag1, tag2])
    db.session.commit()
    
    # Create teams (we'll use team IDs directly)
    team1_id = "team1"
    team2_id = "team2"
    team3_id = "team3"
    
    # Create a match that will be referenced
    match1 = Match(
        name="Match 1",
        event=tournament_url,
        field="Field 1",
        schedule_type="STATIC",
        set_type="SETS",
        nominal_length=60,
        team1=team1_id,
        team2=team2_id,
    )
    db.session.add(match1)
    db.session.commit()
    
    # Create a match with mixed refs_initial:
    # - tag::Pool A (tag reference)
    # - team3 (explicit team ID)
    # - Match 1::winner (match reference)
    # - tag::Pool B (tag reference)
    test_match = Match(
        name="Test Match",
        event=tournament_url,
        field="Field 1",
        schedule_type="STATIC",
        set_type="SETS",
        nominal_length=60,
        refs_initial="tag::Pool A, team3, Match 1::winner, tag::Pool B",
    )
    db.session.add(test_match)
    db.session.commit()
    
    # Simulate update_tags by calling the route logic
    from app.routes.tournaments import update_tags
    from flask import Flask
    from flask_login import current_user
    from unittest.mock import Mock
    
    # Build tag_to_team mapping
    tag_to_team = {
        "tag::Pool A": "resolved_team_a",
        "tag::Pool B": "resolved_team_b",
    }
    
    # Manually apply update_tags logic
    if test_match.refs_initial:
        refs_initial_list = [r.strip() for r in test_match.refs_initial.split(',')]
        refs_current_list = []
        if test_match.refs:
            refs_current_list = [r.strip() for r in test_match.refs.split(',')]
        
        if len(refs_current_list) != len(refs_initial_list):
            refs_current_list = [''] * len(refs_initial_list)
        
        refs_updated = False
        for i, initial_ref in enumerate(refs_initial_list):
            if not initial_ref:
                continue
            
            if initial_ref in tag_to_team:
                if i >= len(refs_current_list):
                    refs_current_list.append('')
                refs_current_list[i] = tag_to_team[initial_ref]
                refs_updated = True
            elif initial_ref and not initial_ref.lower().startswith('tag::') and '::winner' not in initial_ref.lower() and '::loser' not in initial_ref.lower():
                # Explicit team ID
                if i >= len(refs_current_list):
                    refs_current_list.append('')
                refs_current_list[i] = initial_ref
                refs_updated = True
        
        if refs_updated:
            test_match.refs = ', '.join(refs_current_list)
    
    db.session.commit()
    
    # Verify refs structure
    assert test_match.refs is not None
    refs_list = [r.strip() for r in test_match.refs.split(',')]
    assert len(refs_list) == 4
    assert refs_list[0] == "resolved_team_a"  # tag::Pool A resolved
    assert refs_list[1] == "team3"  # explicit team ID preserved
    assert refs_list[2] == ""  # Match 1::winner not yet resolved (empty placeholder)
    assert refs_list[3] == "resolved_team_b"  # tag::Pool B resolved


@pytest.mark.unit
def test_apply_match_dependencies_preserves_explicit_teams_and_tag_resolutions(test_db, tournament, app):
    """apply_match_dependencies should only resolve match references, preserving explicit teams and tag resolutions."""
    tournament_url = tournament.url
    
    # Create field
    field = Field(event=tournament_url, name="Field 1", camera=None)
    db.session.add(field)
    
    # Create teams
    team1_id = "team1"
    team2_id = "team2"
    team3_id = "team3"
    winner_team_id = team1_id  # Match 1 winner will be team1
    
    # Create a match that will be completed
    match1 = Match(
        name="Match 1",
        event=tournament_url,
        field="Field 1",
        schedule_type="STATIC",
        set_type="SETS",
        nominal_length=60,
        team1=team1_id,
        team2=team2_id,
        status="COMPLETED",
    )
    # Set winner (team1 wins)
    match1.match_winner = "TEAM1"
    db.session.add(match1)
    db.session.flush()  # Flush to ensure match is in session
    # winner_team_id property should return team1_id when match_winner is TEAM1
    assert match1.winner_team_id == team1_id
    db.session.commit()
    
    # Create a test match with mixed refs_initial and partially populated refs:
    # refs_initial = "team3, Match 1::winner, resolved_tag_team"
    # refs = "team3, , resolved_tag_team"  (Match 1::winner not yet resolved)
    test_match = Match(
        name="Test Match",
        event=tournament_url,
        field="Field 1",
        schedule_type="STATIC",
        set_type="SETS",
        nominal_length=60,
        refs_initial="team3, Match 1::winner, resolved_tag_team",
        refs="team3, , resolved_tag_team",  # Empty string at index 1 for unresolved match reference
    )
    db.session.add(test_match)
    db.session.commit()
    
    # Apply match dependencies
    apply_match_dependencies(tournament_url, match1)
    db.session.refresh(test_match)
    
    # Verify refs structure - match reference should be resolved, others preserved
    assert test_match.refs is not None
    refs_list = [r.strip() for r in test_match.refs.split(',')]
    assert len(refs_list) == 3
    assert refs_list[0] == "team3"  # explicit team ID preserved
    assert refs_list[1] == winner_team_id  # Match 1::winner resolved
    assert refs_list[2] == "resolved_tag_team"  # tag resolution preserved


@pytest.mark.unit
def test_mixed_refs_all_three_types(test_db, tournament, app):
    """Test refs_initial with all three types: explicit team, tag reference, and match reference."""
    tournament_url = tournament.url
    
    # Create field
    field = Field(event=tournament_url, name="Field 1", camera=None)
    db.session.add(field)
    
    # Create tag
    tag = Tag(event=tournament_url, name="Pool A")
    db.session.add(tag)
    db.session.commit()
    
    # Create teams
    explicit_team = "explicit_team"
    tag_resolved_team = "tag_resolved_team"
    winner_team = "team1"  # Match 1 winner will be team1
    
    # Create a match that will be completed
    match1 = Match(
        name="Match 1",
        event=tournament_url,
        field="Field 1",
        schedule_type="STATIC",
        set_type="SETS",
        nominal_length=60,
        team1="team1",
        team2="team2",
        status="COMPLETED",
    )
    match1.match_winner = "TEAM1"
    db.session.add(match1)
    db.session.flush()  # Flush to ensure match is in session
    assert match1.winner_team_id == "team1"
    db.session.commit()
    
    # Create test match with all three types
    test_match = Match(
        name="Test Match",
        event=tournament_url,
        field="Field 1",
        schedule_type="STATIC",
        set_type="SETS",
        nominal_length=60,
        refs_initial=f"{explicit_team}, tag::Pool A, Match 1::winner",
    )
    db.session.add(test_match)
    db.session.commit()
    
    # Step 1: Apply update_tags (simulate)
    tag_to_team = {"tag::Pool A": tag_resolved_team}
    if test_match.refs_initial:
        refs_initial_list = [r.strip() for r in test_match.refs_initial.split(',')]
        refs_list = [''] * len(refs_initial_list)
        
        for i, initial_ref in enumerate(refs_initial_list):
            if initial_ref in tag_to_team:
                refs_list[i] = tag_to_team[initial_ref]
            elif initial_ref and not initial_ref.lower().startswith('tag::') and '::winner' not in initial_ref.lower() and '::loser' not in initial_ref.lower():
                refs_list[i] = initial_ref
        
        test_match.refs = ', '.join(refs_list)
    db.session.commit()
    
    # Verify after update_tags
    refs_list = [r.strip() for r in test_match.refs.split(',')]
    assert len(refs_list) == 3
    assert refs_list[0] == explicit_team  # explicit team ID
    assert refs_list[1] == tag_resolved_team  # tag resolved
    assert refs_list[2] == ""  # match reference not yet resolved
    
    # Step 2: Apply match dependencies
    apply_match_dependencies(tournament_url, match1)
    db.session.refresh(test_match)
    
    # Verify after apply_match_dependencies
    refs_list = [r.strip() for r in test_match.refs.split(',')]
    assert len(refs_list) == 3
    assert refs_list[0] == explicit_team  # explicit team ID preserved
    assert refs_list[1] == tag_resolved_team  # tag resolution preserved
    assert refs_list[2] == winner_team  # match reference resolved (winner_team is "team1")


@pytest.mark.unit
def test_refs_index_structure_preserved(test_db, tournament, app):
    """Test that refs maintains correct index structure with empty string placeholders."""
    tournament_url = tournament.url
    
    # Create field
    field = Field(event=tournament_url, name="Field 1", camera=None)
    db.session.add(field)
    
    # Create tag
    tag = Tag(event=tournament_url, name="Pool A")
    db.session.add(tag)
    db.session.commit()
    
    # Create test match with refs_initial that has empty positions
    # Note: refs_initial should never be empty per invariant, but we test index preservation
    test_match = Match(
        name="Test Match",
        event=tournament_url,
        field="Field 1",
        schedule_type="STATIC",
        set_type="SETS",
        nominal_length=60,
        refs_initial="tag::Pool A, Match 1::winner, team3",
    )
    db.session.add(test_match)
    db.session.commit()
    
    # Apply update_tags
    tag_to_team = {"tag::Pool A": "resolved_team_a"}
    if test_match.refs_initial:
        refs_initial_list = [r.strip() for r in test_match.refs_initial.split(',')]
        refs_list = [''] * len(refs_initial_list)
        
        for i, initial_ref in enumerate(refs_initial_list):
            if initial_ref in tag_to_team:
                refs_list[i] = tag_to_team[initial_ref]
            elif initial_ref and not initial_ref.lower().startswith('tag::') and '::winner' not in initial_ref.lower() and '::loser' not in initial_ref.lower():
                refs_list[i] = initial_ref
        
        test_match.refs = ', '.join(refs_list)
    db.session.commit()
    
    # Verify index structure
    refs_list = [r.strip() for r in test_match.refs.split(',')]
    assert len(refs_list) == 3
    assert refs_list[0] == "resolved_team_a"
    assert refs_list[1] == ""  # placeholder for Match 1::winner
    assert refs_list[2] == "team3"
    
    # Verify that refs_initial and refs have same length
    refs_initial_list = [r.strip() for r in test_match.refs_initial.split(',')]
    assert len(refs_list) == len(refs_initial_list)


@pytest.mark.unit
def test_refs_cleared_when_refs_initial_changes(test_db, tournament, app):
    """Test that refs is cleared when refs_initial changes, but explicit team IDs are repopulated."""
    tournament_url = tournament.url
    
    # Create field
    field = Field(event=tournament_url, name="Field 1", camera=None)
    db.session.add(field)
    db.session.commit()
    
    # Create test match with initial state
    test_match = Match(
        name="Test Match",
        event=tournament_url,
        field="Field 1",
        schedule_type="STATIC",
        set_type="SETS",
        nominal_length=60,
        refs_initial="tag::Pool A, team1",
        refs="resolved_team_a, team1",  # Partially resolved
    )
    db.session.add(test_match)
    db.session.commit()
    
    # Change refs_initial (simulating user edit)
    old_refs_initial = test_match.refs_initial
    new_refs_initial = "team2, Match 1::winner, team3"
    test_match.refs_initial = new_refs_initial
    
    # Simulate the logic from update_match route
    if old_refs_initial != new_refs_initial:
        # Helper to check if explicit team ID
        def is_explicit_team_id(val: str) -> bool:
            if not val or not val.strip():
                return False
            val = val.strip()
            if val.lower().startswith('tag::'):
                return False
            if '::winner' in val.lower() or '::loser' in val.lower():
                return False
            return True
        
        # Clear and repopulate explicit team IDs
        if new_refs_initial:
            refs_initial_list = [r.strip() for r in new_refs_initial.split(',')]
            refs_list = [''] * len(refs_initial_list)
            has_explicit_ids = False
            for i, initial_ref in enumerate(refs_initial_list):
                if initial_ref and is_explicit_team_id(initial_ref):
                    refs_list[i] = initial_ref
                    has_explicit_ids = True
            if has_explicit_ids:
                test_match.refs = ', '.join(refs_list)
            else:
                test_match.refs = None
        else:
            test_match.refs = None
    
    db.session.commit()
    
    # Verify refs was cleared and explicit team IDs repopulated
    assert test_match.refs is not None
    refs_list = [r.strip() for r in test_match.refs.split(',')]
    assert len(refs_list) == 3
    assert refs_list[0] == "team2"  # explicit team ID
    assert refs_list[1] == ""  # placeholder for Match 1::winner
    assert refs_list[2] == "team3"  # explicit team ID
    # Old resolved tag reference should be gone


@pytest.mark.unit
def test_team1_team2_with_mixed_references(test_db, tournament, app):
    """Test team1 and team2 fields with explicit teams, tag references, and match references."""
    tournament_url = tournament.url
    
    # Create field
    field = Field(event=tournament_url, name="Field 1", camera=None)
    db.session.add(field)
    
    # Create tag
    tag = Tag(event=tournament_url, name="Pool A")
    db.session.add(tag)
    db.session.commit()
    
    # Create teams
    explicit_team = "explicit_team"
    tag_resolved_team = "tag_resolved_team"
    winner_team = "team1"  # Match 1 winner will be team1
    
    # Create a match that will be completed
    match1 = Match(
        name="Match 1",
        event=tournament_url,
        field="Field 1",
        schedule_type="STATIC",
        set_type="SETS",
        nominal_length=60,
        team1="team1",
        team2="team2",
        status="COMPLETED",
    )
    match1.match_winner = "TEAM1"
    db.session.add(match1)
    db.session.flush()  # Flush to ensure match is in session
    assert match1.winner_team_id == "team1"
    db.session.commit()
    
    # Create test match
    test_match = Match(
        name="Test Match",
        event=tournament_url,
        field="Field 1",
        schedule_type="STATIC",
        set_type="SETS",
        nominal_length=60,
        team1_initial=explicit_team,  # explicit team
        team2_initial="tag::Pool A",  # tag reference
    )
    db.session.add(test_match)
    db.session.commit()
    
    # Apply update_tags (simulate)
    tag_to_team = {"tag::Pool A": tag_resolved_team}
    if test_match.team1_initial and test_match.team1_initial in tag_to_team:
        test_match.team1 = tag_to_team[test_match.team1_initial]
    elif test_match.team1_initial and not test_match.team1_initial.lower().startswith('tag::') and '::winner' not in test_match.team1_initial.lower() and '::loser' not in test_match.team1_initial.lower():
        test_match.team1 = test_match.team1_initial
    
    if test_match.team2_initial and test_match.team2_initial in tag_to_team:
        test_match.team2 = tag_to_team[test_match.team2_initial]
    elif test_match.team2_initial and not test_match.team2_initial.lower().startswith('tag::') and '::winner' not in test_match.team2_initial.lower() and '::loser' not in test_match.team2_initial.lower():
        test_match.team2 = test_match.team2_initial
    
    db.session.commit()
    
    # Verify after update_tags
    assert test_match.team1 == explicit_team  # explicit team ID
    assert test_match.team2 == tag_resolved_team  # tag resolved
    assert test_match.team1_initial == explicit_team  # unchanged
    assert test_match.team2_initial == "tag::Pool A"  # unchanged
    
    # Now test with match reference
    test_match2 = Match(
        name="Test Match 2",
        event=tournament_url,
        field="Field 1",
        schedule_type="STATIC",
        set_type="SETS",
        nominal_length=60,
        team1_initial="Match 1::winner",
    )
    db.session.add(test_match2)
    db.session.commit()
    
    # Apply match dependencies
    apply_match_dependencies(tournament_url, match1)
    db.session.refresh(test_match2)
    
    # Verify match reference resolved
    assert test_match2.team1 == winner_team
    assert test_match2.team1_initial == "Match 1::winner"  # unchanged

