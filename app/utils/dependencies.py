"""
Utility functions for resolving match dependencies.
"""

from __future__ import annotations

from app.services.dual_write import get_match_referee_rows
from models import Match, db


def apply_match_dependencies(tournament_url: str, completed_match: Match) -> None:
    """Resolve winner/loser placeholders for all matches that depended on *completed_match*.

    Scans every match in the tournament and replaces ``"<name>::winner"`` and
    ``"<name>::loser"`` placeholders in ``team1_initial``, ``team2_initial``,
    and unresolved referee slots with the concrete team IDs from
    *completed_match*, writing the result to ``team1`` / ``team2`` and to
    the ``team_id`` column of the corresponding ``MatchReferee`` rows.

    This function is called after a match is finalised so that downstream
    matches can have their rosters and refs resolved in preparation for
    starting.

    Args:
        tournament_url: URL slug of the tournament; used to scope queries.
        completed_match: The match that just finished, whose winner/loser team
            IDs should be propagated to dependent matches.
    """
    winner_team_id = completed_match.winner_team_id
    loser_team_id = completed_match.loser_team_id
    if not winner_team_id and not loser_team_id:
        return

    def normalize(s: str) -> str:
        return " ".join((s or "").strip().split())

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
            if normalize(initial) == winner_placeholder and winner_team_id:
                m.team1 = winner_team_id
                updated_any = True
            elif normalize(initial) == loser_placeholder and loser_team_id:
                m.team1 = loser_team_id
                updated_any = True

        # team2
        if not m.team2 and m.team2_initial:
            initial = m.team2_initial.strip()
            if normalize(initial) == winner_placeholder and winner_team_id:
                m.team2 = winner_team_id
                updated_any = True
            elif normalize(initial) == loser_placeholder and loser_team_id:
                m.team2 = loser_team_id
                updated_any = True

        # refs — resolve placeholder slots whose team_id has not yet been set
        for row in get_match_referee_rows(m):
            if row.team_id:
                continue
            normalized_ref = normalize(row.initial)
            if normalized_ref == winner_placeholder and winner_team_id:
                row.team_id = winner_team_id
                updated_any = True
            elif normalized_ref == loser_placeholder and loser_team_id:
                row.team_id = loser_team_id
                updated_any = True

    if updated_any:
        db.session.commit()
