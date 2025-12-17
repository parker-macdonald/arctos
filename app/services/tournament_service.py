"""
Tournament-oriented application services.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from app.services.permission_service import PermissionService
from app.utils.user_helpers import is_player, is_team
from app.error_values import Some


@dataclass(frozen=True)
class TournamentService:
    @staticmethod
    def get_homepage_context(user=None) -> Dict[str, Any]:
        """
        Build the homepage context for `templates/index.html`.

        Keeps current template contract stable:
        - tournaments
        - to_tournaments (legacy, unused)
        - team_counts
        - user_reg_status
        """
        from models import Tournament, TeamRegistration, PlayerRegistration, TO, db

        published_tournaments = Tournament.query.filter_by(published=True).all()

        to_tournament_urls: list[str] = []
        if user is not None and getattr(user, "is_authenticated", False):
            match PermissionService.user_type(user):
                case Some(user_type):
                    to_entries = TO.query.filter_by(user_id=user.id, user_type=user_type).all()
                    to_tournament_urls = [entry.event for entry in to_entries]
                case _:
                    pass

        all_tournament_urls = {t.url for t in published_tournaments}
        all_tournament_urls.update(to_tournament_urls or [])

        tournaments = (
            Tournament.query.filter(Tournament.url.in_(list(all_tournament_urls)))
            .order_by(Tournament.start_date.asc())
            .all()
        )

        # Compute registered team counts per tournament (single grouped query)
        from sqlalchemy import func

        team_counts: Dict[str, int] = {t.url: 0 for t in tournaments}
        if tournaments:
            counts = (
                db.session.query(TeamRegistration.event, func.count(TeamRegistration.id))
                .filter(TeamRegistration.status == "CONFIRMED")
                .filter(TeamRegistration.event.in_([t.url for t in tournaments]))
                .group_by(TeamRegistration.event)
                .all()
            )
            for event, count in counts:
                team_counts[event] = int(count or 0)

        user_reg_status: Dict[str, Any] = {}
        if user is not None and getattr(user, "is_authenticated", False):
            for t in tournaments:
                if is_team(user):
                    reg = TeamRegistration.query.filter_by(event=t.url, team=user.id).first()
                    if reg:
                        user_reg_status[t.url] = {
                            "type": "team",
                            "status": reg.status or "",
                            "paid": bool(reg.paid),
                            "amount_paid": reg.amount_paid or 0.0,
                        }
                elif is_player(user):
                    reg = PlayerRegistration.query.filter_by(event=t.url, player=user.id).first()
                    if reg:
                        user_reg_status[t.url] = {
                            "type": "player",
                            "status": reg.status or "",
                            "paid": bool(reg.paid),
                            "amount_paid": reg.amount_paid or 0.0,
                        }

        return {
            "tournaments": tournaments,
            "to_tournaments": [],  # legacy
            "team_counts": team_counts,
            "user_reg_status": user_reg_status,
        }


