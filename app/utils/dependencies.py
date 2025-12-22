"""
Utility functions for resolving match dependencies.
"""

from __future__ import annotations

from models import Match, db


def apply_match_dependencies(tournament_url: str, completed_match: Match) -> None:
    """Replace placeholders like 'MatchName winner/loser' in other matches' initial fields
    with explicit team ids in non-initial fields (team1/team2/refs)."""
    # Determine winner/loser team ids
    winner_team_id = completed_match.winner_team_id
    loser_team_id = completed_match.loser_team_id
    if not winner_team_id and not loser_team_id:
        return

    # If either missing, nothing to substitute
    if not winner_team_id or not loser_team_id:
        pass  # Still proceed for what exists

    # Build robust placeholder variants (case-insensitive, flexible separators)
    def normalize(s: str) -> str:
        return ' '.join((s or '').strip().split())

    base_name = completed_match.name
    winner_placeholder = f"{base_name}::winner"
    loser_placeholder = f"{base_name}::loser"

    dependent_matches = Match.query.filter_by(event=tournament_url).all()
    updated_any = False
    for m in dependent_matches:
        if m.uuid == completed_match.uuid:
            continue

        # team1
        if not m.team1 and m.team1_initial:
            initial = m.team1_initial.strip()
            if normalize(initial)==winner_placeholder and winner_team_id:
                m.team1 = winner_team_id
                updated_any = True
            elif normalize(initial)==loser_placeholder and loser_team_id:
                m.team1 = loser_team_id
                updated_any = True

        # team2
        if not m.team2 and m.team2_initial:
            initial = m.team2_initial.strip()
            if normalize(initial)==winner_placeholder and winner_team_id:
                m.team2 = winner_team_id
                updated_any = True
            elif normalize(initial)==loser_placeholder and loser_team_id:
                m.team2 = loser_team_id
                updated_any = True

        # refs - merge match resolutions into existing refs at correct indices
        refs_initial_val = m.refs_initial or ''
        if refs_initial_val:
            # Split refs_initial preserving all positions (including empty strings between commas)
            refs_initial_list = [r.strip() for r in refs_initial_val.split(',')]
            
            # Get current refs state (may be empty or partially populated with empty string placeholders)
            refs_current_list = []
            if m.refs:
                refs_current_list = [r.strip() for r in m.refs.split(',')]
            
            # Ensure refs_current_list has same length as refs_initial_list
            # If lengths don't match, rebuild from refs_initial (preserving explicit team IDs)
            if len(refs_current_list) != len(refs_initial_list):
                refs_current_list = [''] * len(refs_initial_list)
                # Populate any explicit team IDs from refs_initial
                for i, initial_ref in enumerate(refs_initial_list):
                    if initial_ref and not initial_ref.lower().startswith('tag::') and '::winner' not in initial_ref.lower() and '::loser' not in initial_ref.lower():
                        # Explicit team ID
                        refs_current_list[i] = initial_ref
            
            # Merge match resolutions into existing refs at correct indices
            changed = False
            for i, initial_ref in enumerate(refs_initial_list):
                if not initial_ref:
                    continue
                
                # Check if this is a match reference that needs resolution
                normalized_ref = normalize(initial_ref)
                if normalized_ref == winner_placeholder and winner_team_id:
                    # Only update if this position is empty (not already resolved)
                    if i < len(refs_current_list) and not refs_current_list[i]:
                        refs_current_list[i] = winner_team_id
                        changed = True
                elif normalized_ref == loser_placeholder and loser_team_id:
                    # Only update if this position is empty (not already resolved)
                    if i < len(refs_current_list) and not refs_current_list[i]:
                        refs_current_list[i] = loser_team_id
                        changed = True
                # For tag references or explicit team IDs, preserve existing value
                # (they should have been set by update_tags or are already correct)
            
            if changed:
                # Join with commas, preserving empty strings as placeholders
                m.refs = ', '.join(refs_current_list)
                updated_any = True

    if updated_any:
        db.session.commit()

