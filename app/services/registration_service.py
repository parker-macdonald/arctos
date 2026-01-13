"""
Tournament registration workflows.

This service centralizes the multi-model workflow logic for registering and
de-registering teams/players for a tournament.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from app.error_values import Err, Ok, Result, allow_Q, option
from app.exceptions import (
    ArctosError,
    RegistrationClosedError,
    TournamentNotFoundError,
    ValidationError,
)

if TYPE_CHECKING:  # pragma: no cover
    from models import PlayerRegistration, TeamRegistration, Tournament


@dataclass(frozen=True)
class RegistrationService:
    @staticmethod
    def _get_tournament(tournament_url: str) -> Result["Tournament", ArctosError]:
        from models import Tournament

        tournament = Tournament.query.filter_by(url=tournament_url).first()
        return option(tournament).ok_or(TournamentNotFoundError(tournament_url))

    @staticmethod
    def _require_registration_open_for_register(
        tournament,
    ) -> Result[None, ArctosError]:
        if not getattr(tournament, "registration_open", False):
            return Err(
                RegistrationClosedError("Registration is not open for this tournament")
            )
        return Ok(None)

    @staticmethod
    def _require_registration_open_for_deregister(
        tournament,
    ) -> Result[None, ArctosError]:
        if not getattr(tournament, "registration_open", False):
            return Err(
                ValidationError(
                    "Registration changes are locked. You can no longer deregister."
                )
            )
        return Ok(None)

    @staticmethod
    @allow_Q
    def register_team(
        tournament_url: str, team_id: str, pseudonym: str
    ) -> Result["TeamRegistration", ArctosError]:
        from models import TeamRegistration, db

        tournament = RegistrationService._get_tournament(tournament_url).Q()
        RegistrationService._require_registration_open_for_register(tournament).Q()

        pseudonym = (pseudonym or "").strip()
        if not pseudonym:
            return Err(ValidationError("Team pseudonym is required"))
        if "::" in pseudonym:
            return Err(ValidationError('Team pseudonyms cannot contain "::"'))

        existing_reg = TeamRegistration.query.filter_by(
            event=tournament_url, team=team_id, status="CONFIRMED"
        ).first()
        if existing_reg:
            return Err(
                ValidationError("Your team is already registered for this tournament")
            )

        if tournament.n_max_teams:
            current_team_count = TeamRegistration.query.filter_by(
                event=tournament_url, status="CONFIRMED"
            ).count()
            if current_team_count >= tournament.n_max_teams:
                return Err(
                    ValidationError(
                        f"Maximum number of teams ({tournament.n_max_teams}) already registered"
                    )
                )

        team_registration = TeamRegistration(
            event=tournament_url, team=team_id, pseudonym=pseudonym
        )

        # Auto-mark as paid if registration fee is zero
        if not tournament.team_reg_fee or tournament.team_reg_fee == 0:
            team_registration.paid = True
            team_registration.amount_paid = 0.0
            team_registration.paid_at = datetime.now(timezone.utc).replace(tzinfo=None)

        db.session.add(team_registration)
        db.session.commit()
        return Ok(team_registration)

    @staticmethod
    @allow_Q
    def register_player(
        tournament_url: str,
        player_id: str,
        team_id: Optional[str],
        *,
        jersey_number: str = "",
        jersey_name: str = "",
    ) -> Result["PlayerRegistration", ArctosError]:
        from models import PlayerRegistration, db

        tournament = RegistrationService._get_tournament(tournament_url).Q()
        RegistrationService._require_registration_open_for_register(tournament).Q()

        existing_reg = PlayerRegistration.query.filter_by(
            event=tournament_url, player=player_id
        ).first()

        team_id = (team_id or "").strip() or None
        status = "CONFIRMED" if not team_id else "PENDING_TEAM_APPROVAL"

        # Enforce exactly one PlayerRegistration row per (event, player).
        # If a player was previously rejected/cancelled, allow resubmission by updating that row.
        if existing_reg:
            if existing_reg.status not in ("REJECTED", "CANCELLED"):
                return Err(
                    ValidationError(
                        "You already have a registration for this tournament"
                    )
                )
            player_registration = existing_reg
            player_registration.team = team_id
            player_registration.jersey_number = jersey_number or ""
            player_registration.jersey_name = jersey_name or ""
            player_registration.status = status
        else:
            player_registration = PlayerRegistration(
                event=tournament_url,
                player=player_id,
                team=team_id,
                jersey_number=jersey_number or "",
                jersey_name=jersey_name or "",
                status=status,
            )

        # Auto-mark as paid if registration fee is zero
        if not tournament.player_reg_fee or tournament.player_reg_fee == 0:
            player_registration.paid = True
            player_registration.amount_paid = 0.0
            player_registration.paid_at = datetime.now(timezone.utc).replace(
                tzinfo=None
            )

        db.session.add(player_registration)

        db.session.commit()
        return Ok(player_registration)

    @staticmethod
    @allow_Q
    def deregister_team(tournament_url: str, team_id: str) -> Result[None, ArctosError]:
        from models import Tournament, TeamRegistration, PlayerRegistration, db

        tournament = RegistrationService._get_tournament(tournament_url).Q()
        RegistrationService._require_registration_open_for_deregister(tournament).Q()

        team_registration = TeamRegistration.query.filter_by(
            event=tournament_url, team=team_id, status="CONFIRMED"
        ).first()
        if not team_registration:
            return Err(ValidationError("You are not registered for this tournament"))

        team_registration.status = "CANCELLED"

        PlayerRegistration.query.filter_by(event=tournament_url, team=team_id).update(
            {"status": "CANCELLED"}
        )

        db.session.commit()
        return Ok(None)

    @staticmethod
    @allow_Q
    def deregister_player(
        tournament_url: str, player_id: str
    ) -> Result[None, ArctosError]:
        from models import Tournament, PlayerRegistration, db

        tournament = RegistrationService._get_tournament(tournament_url).Q()
        RegistrationService._require_registration_open_for_deregister(tournament).Q()

        player_registration = (
            PlayerRegistration.query.filter_by(event=tournament_url, player=player_id)
            .filter(
                PlayerRegistration.status.in_(["PENDING_TEAM_APPROVAL", "CONFIRMED"])
            )
            .first()
        )
        if not player_registration:
            return Err(ValidationError("You are not registered for this tournament"))

        player_registration.status = "CANCELLED"

        db.session.commit()
        return Ok(None)
