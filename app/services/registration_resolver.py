"""
RegistrationResolver: centralizes queries for teams/players registered for a tournament.

Supports both standalone tournaments (event=tournament.url) and league tournaments
(league_id=tournament.league_id). Single source of truth for registration queries.
"""

from __future__ import annotations

from typing import List, Optional

from app.domain.enums import RegistrationStatus, TeamRegistrationStatus


def _registrable_filter(tournament):
    """Return (event, league_id) for querying. Exactly one is non-None."""
    if tournament.league_id:
        return None, tournament.league_id
    return tournament.url, None


def team_registration_for_tournament(tournament, team_id: str):
    """Single team registration for (tournament, team_id), or None."""
    from models import TeamRegistration

    event, league_id = _registrable_filter(tournament)
    if league_id is not None:
        return (
            TeamRegistration.query.filter_by(
                league_id=league_id,
                team=team_id,
                status=TeamRegistrationStatus.CONFIRMED,
            )
            .first()
        )
    return TeamRegistration.query.filter_by(
        event=event, team=team_id, status=TeamRegistrationStatus.CONFIRMED
    ).first()


def team_registrations_for_tournament(
    tournament, status=TeamRegistrationStatus.CONFIRMED, exclude_cancelled=False
):
    """Team registrations for this tournament (event or league)."""
    from models import TeamRegistration

    event, league_id = _registrable_filter(tournament)
    q = TeamRegistration.query
    if league_id is not None:
        q = q.filter_by(league_id=league_id)
    else:
        q = q.filter_by(event=event)
    if exclude_cancelled:
        q = q.filter(TeamRegistration.status != TeamRegistrationStatus.CANCELLED)
    else:
        q = q.filter_by(status=status)
    return q.all()


def player_registrations_for_tournament(
    tournament,
    team_id=None,
    unattached_only=False,
    statuses=None,
):
    """Player registrations for this tournament. If team_id given, filter by team. If unattached_only, filter for team IS NULL."""
    from models import PlayerRegistration

    if statuses is None:
        statuses = [RegistrationStatus.PENDING_TEAM_APPROVAL, RegistrationStatus.CONFIRMED]

    event, league_id = _registrable_filter(tournament)
    q = PlayerRegistration.query
    if league_id is not None:
        q = q.filter_by(league_id=league_id)
    else:
        q = q.filter_by(event=event)
    q = q.filter(PlayerRegistration.status.in_(statuses))
    if unattached_only:
        q = q.filter(PlayerRegistration.team.is_(None))
    elif team_id is not None:
        q = q.filter_by(team=team_id)
    return q.all()


def is_team_registered(tournament, team_id: str) -> bool:
    """True if team is registered for this tournament (event or league)."""
    from models import TeamRegistration

    event, league_id = _registrable_filter(tournament)
    if league_id is not None:
        return (
            TeamRegistration.query.filter_by(
                league_id=league_id,
                team=team_id,
                status=TeamRegistrationStatus.CONFIRMED,
            ).first()
            is not None
        )
    return (
        TeamRegistration.query.filter_by(
            event=event, team=team_id, status=TeamRegistrationStatus.CONFIRMED
        ).first()
        is not None
    )


def player_registration_for_tournament(tournament, player_id: str):
    """Single player registration for (tournament, player_id), or None."""
    from models import PlayerRegistration

    prs = player_registrations_for_tournament(
        tournament,
        statuses=[
            RegistrationStatus.PENDING_TEAM_APPROVAL,
            RegistrationStatus.CONFIRMED,
        ],
    )
    for pr in prs:
        if pr.player == player_id:
            return pr
    return None


def is_player_registered(tournament, player_id: str) -> bool:
    """True if player has a registration (pending or confirmed) for this tournament."""
    from models import PlayerRegistration

    event, league_id = _registrable_filter(tournament)
    if league_id is not None:
        q = (
            PlayerRegistration.query.filter_by(
                league_id=league_id, player=player_id
            )
            .filter(
                PlayerRegistration.status.in_(
                    [
                        RegistrationStatus.PENDING_TEAM_APPROVAL,
                        RegistrationStatus.CONFIRMED,
                    ]
                )
            )
        )
    else:
        q = PlayerRegistration.query.filter_by(event=event, player=player_id).filter(
            PlayerRegistration.status.in_(
                [
                    RegistrationStatus.PENDING_TEAM_APPROVAL,
                    RegistrationStatus.CONFIRMED,
                ]
            )
        )
    return q.first() is not None


def to_entries_for_tournament(tournament):
    """TO rows for this tournament (event-specific or league-season TOs)."""
    from models import TO

    if tournament.league_id:
        return TO.query.filter_by(league_id=tournament.league_id).all()
    return TO.query.filter_by(event=tournament.url).all()
