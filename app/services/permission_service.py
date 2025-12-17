"""
Authorization and permission checks.

This service is intentionally Flask-agnostic: it does not use `current_user`,
`request`, or `flash`. Callers (routes/decorators) handle UI/HTTP concerns.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.utils.user_helpers import is_player, is_team
from app.error_values import Null, Option, Some


@dataclass(frozen=True)
class PermissionService:
    @staticmethod
    def user_type(user) -> Option[str]:
        """Return Some('player'|'team') for supported users; otherwise Null()."""
        if user is None:
            return Null()
        if is_player(user):
            return Some("player")
        if is_team(user):
            return Some("team")
        return Null()

    @staticmethod
    def is_tournament_organizer(tournament_url: str, user) -> bool:
        """True if user is a TO for the tournament."""
        if not tournament_url or user is None:
            return False
        match PermissionService.user_type(user):
            case Some(user_type):
                pass
            case _:
                return False

        from models import TO

        return (
            TO.query.filter_by(user_id=user.id, user_type=user_type, event=tournament_url).first()
            is not None
        )

    @staticmethod
    def can_view_tournament(tournament_url: str, user) -> bool:
        """True if tournament is published or user is a TO."""
        from models import Tournament

        tournament = Tournament.query.get(tournament_url)
        if not tournament:
            return False
        if tournament.published:
            return True
        return PermissionService.is_tournament_organizer(tournament_url, user)

    @staticmethod
    def can_head_ref_match(tournament_url: str, user, match=None) -> bool:
        """Delegate to existing head-ref policy logic for now (to avoid behavior drift)."""
        if user is None or not is_player(user):
            return False
        from app.utils.helpers import can_head_ref_match as _can_head_ref_match

        return _can_head_ref_match(tournament_url, user.id, match=match)


