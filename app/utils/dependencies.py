"""
Utility functions for resolving match dependencies.
"""
import json
from models import Match, db


def apply_match_dependencies(tournament_url: str, completed_match: Match) -> None:
    """Replace placeholders like 'MatchName winner/loser' in other matches' initial fields
    with explicit team ids in non-initial fields (team1/team2/refs)."""
    # Determine winner/loser team ids
    winner_key = None
    try:
        gs = json.loads(completed_match.gamestate) if completed_match.gamestate else {}
        winner_key = gs.get('match_winner')  # 'TEAM1' or 'TEAM2'
    except Exception:
        winner_key = None

    if winner_key not in ('TEAM1', 'TEAM2'):
        return

    winner_team_id = completed_match.team1 if winner_key == 'TEAM1' else completed_match.team2
    loser_team_id = completed_match.team2 if winner_key == 'TEAM1' else completed_match.team1

    # If either missing, nothing to substitute
    if not winner_team_id or not loser_team_id:
        pass  # Still proceed for what exists

    # Build robust placeholder variants (case-insensitive, flexible separators)
    def normalize(s: str) -> str:
        return ' '.join((s or '').strip().lower().split())

    base_name = completed_match.name
    winner_placeholder = f"{base_name} winner"
    loser_placeholder = f"{base_name} loser"
    winner_alternates = set([
        normalize(winner_placeholder),
        normalize(f"{base_name} - winner"),
        normalize(f"{base_name} (winner)"),
        normalize(f"{completed_match.uuid} winner"),
    ])
    loser_alternates = set([
        normalize(loser_placeholder),
        normalize(f"{base_name} - loser"),
        normalize(f"{base_name} (loser)"),
        normalize(f"{completed_match.uuid} loser"),
    ])

    dependent_matches = Match.query.filter_by(event=tournament_url).all()
    updated_any = False
    for m in dependent_matches:
        if m.uuid == completed_match.uuid:
            continue

        # team1
        if not m.team1 and m.team1_initial:
            initial = m.team1_initial.strip()
            if normalize(initial) in winner_alternates and winner_team_id:
                m.team1 = winner_team_id
                updated_any = True
            elif normalize(initial) in loser_alternates and loser_team_id:
                m.team1 = loser_team_id
                updated_any = True

        # team2
        if not m.team2 and m.team2_initial:
            initial = m.team2_initial.strip()
            if normalize(initial) in winner_alternates and winner_team_id:
                m.team2 = winner_team_id
                updated_any = True
            elif normalize(initial) in loser_alternates and loser_team_id:
                m.team2 = loser_team_id
                updated_any = True

        # refs
        refs_initial_val = m.refs_initial or ''
        if refs_initial_val:
            # Only populate refs if not already explicitly set or still contains placeholders
            refs_current = (m.refs or '').strip()
            refs_list = [r.strip() for r in refs_initial_val.split(',') if r.strip() != '']
            resolved = []
            changed = False
            for r in refs_list:
                if normalize(r) in winner_alternates and winner_team_id:
                    resolved.append(winner_team_id)
                    changed = True
                elif normalize(r) in loser_alternates and loser_team_id:
                    resolved.append(loser_team_id)
                    changed = True
                else:
                    resolved.append(r)
            # If we changed anything or refs is empty, set refs to resolved string
            if changed or not refs_current:
                m.refs = ', '.join(resolved)
                updated_any = True

    if updated_any:
        db.session.commit()

