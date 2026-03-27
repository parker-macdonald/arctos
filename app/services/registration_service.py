"""
Tournament registration workflows.

This service centralizes the multi-model workflow logic for registering and
de-registering teams/players for a tournament.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from app.domain.enums import MatchStatus, RegistrationStatus, TeamRegistrationStatus
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
    def _tournament_team_reg_open(tournament) -> bool:
        from app.utils.helpers import get_registrable_config

        cfg = get_registrable_config(tournament)
        if not cfg:
            return False
        # Prefer new field; fall back to legacy registration_open for older data.
        if hasattr(cfg, "team_registration_open"):
            return bool(cfg.team_registration_open)
        return bool(cfg.registration_open)

    @staticmethod
    def _tournament_player_reg_open(tournament) -> bool:
        from app.utils.helpers import get_registrable_config

        cfg = get_registrable_config(tournament)
        if not cfg:
            return False
        if hasattr(cfg, "player_registration_open"):
            return bool(cfg.player_registration_open)
        return bool(cfg.registration_open)

    @staticmethod
    def _require_team_registration_open_for_register(
        tournament,
    ) -> Result[None, ArctosError]:
        if not RegistrationService._tournament_team_reg_open(tournament):
            return Err(
                RegistrationClosedError("Team registration is not open for this tournament")
            )
        return Ok(None)

    @staticmethod
    def _require_player_registration_open_for_register(
        tournament,
    ) -> Result[None, ArctosError]:
        if not RegistrationService._tournament_player_reg_open(tournament):
            return Err(
                RegistrationClosedError("Player registration is not open for this tournament")
            )
        return Ok(None)

    @staticmethod
    def _require_team_registration_open_for_deregister(
        tournament,
    ) -> Result[None, ArctosError]:
        if not RegistrationService._tournament_team_reg_open(tournament):
            return Err(
                ValidationError(
                    "Registration changes are locked. You can no longer deregister teams."
                )
            )
        return Ok(None)

    @staticmethod
    def _require_player_registration_open_for_deregister(
        tournament,
    ) -> Result[None, ArctosError]:
        if not RegistrationService._tournament_player_reg_open(tournament):
            return Err(
                ValidationError(
                    "Registration changes are locked. You can no longer deregister players."
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
        RegistrationService._require_team_registration_open_for_register(tournament).Q()

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

        from app.utils.helpers import get_registrable_config
        cfg = get_registrable_config(tournament)
        n_max = getattr(cfg, "n_max_teams", None) if cfg else None
        if n_max is not None:
            # For league tournaments, team registrations are stored on league_id.
            if getattr(tournament, "league_id", None):
                current_team_count = TeamRegistration.query.filter_by(
                    league_id=tournament.league_id,
                    status=TeamRegistrationStatus.CONFIRMED,
                ).count()
            else:
                current_team_count = TeamRegistration.query.filter_by(
                    event=tournament_url,
                    status=TeamRegistrationStatus.CONFIRMED,
                ).count()
            if current_team_count >= n_max:
                return Err(
                    ValidationError(
                        f"Maximum number of teams ({n_max}) already registered"
                    )
                )

        team_registration = TeamRegistration(
            event=tournament_url, team=team_id, pseudonym=pseudonym
        )

        # Auto-mark as paid if registration fee is zero
        from app.utils.helpers import get_registrable_config
        cfg = get_registrable_config(tournament)
        if not cfg or not cfg.team_reg_fee or cfg.team_reg_fee == 0:
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
        waiver_legal_name_signature: str = "",
    ) -> Result["PlayerRegistration", ArctosError]:
        from models import PlayerRegistration, db

        tournament = RegistrationService._get_tournament(tournament_url).Q()
        RegistrationService._require_player_registration_open_for_register(tournament).Q()

        existing_reg = PlayerRegistration.query.filter_by(
            event=tournament_url, player=player_id
        ).first()

        team_id = (team_id or "").strip() or None
        status = (
            RegistrationStatus.CONFIRMED
            if not team_id
            else RegistrationStatus.PENDING_TEAM_APPROVAL
        )

        # Enforce exactly one PlayerRegistration row per (event, player).
        # If a player was previously rejected/cancelled, allow resubmission by updating that row.
        if existing_reg:
            if existing_reg.status not in (
                RegistrationStatus.REJECTED,
                RegistrationStatus.CANCELLED,
            ):
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
        from app.utils.helpers import get_registrable_config
        cfg = get_registrable_config(tournament)
        if not cfg or not cfg.player_reg_fee or cfg.player_reg_fee == 0:
            player_registration.paid = True
            player_registration.amount_paid = 0.0
            player_registration.paid_at = datetime.now(timezone.utc).replace(
                tzinfo=None
            )

        # If a waiver is configured, players must sign it.
        waiver_filepath = getattr(cfg, "waiver_filepath", None) if cfg else None
        if waiver_filepath:
            signature = (waiver_legal_name_signature or "").strip()
            if not signature:
                return Err(ValidationError("Waiver signature is required"))
            current_waiver_sha = getattr(cfg, "waiver_sha256", None)
            if not current_waiver_sha:
                return Err(ValidationError("Waiver is missing its checksum"))

            now = datetime.now(timezone.utc).replace(tzinfo=None)
            player_registration.waiver_legal_name_signature = signature
            player_registration.waiver_legal_name_signature_sha256 = current_waiver_sha
            player_registration.waiver_signature_submitted_at = now

        db.session.add(player_registration)

        db.session.commit()
        return Ok(player_registration)

    @staticmethod
    @allow_Q
    def deregister_team(tournament_url: str, team_id: str) -> Result[None, ArctosError]:
        from models import Match, Tournament, TeamRegistration, PlayerRegistration, db

        tournament = RegistrationService._get_tournament(tournament_url).Q()
        RegistrationService._require_team_registration_open_for_deregister(tournament).Q()

        team_registration = TeamRegistration.query.filter_by(
            event=tournament_url, team=team_id, status=RegistrationStatus.CONFIRMED
        ).first()
        if not team_registration:
            return Err(ValidationError("You are not registered for this tournament"))

        in_progress = (
            Match.query.filter_by(event=tournament_url, status=MatchStatus.IN_PROGRESS)
            .filter(
                (Match.team1 == team_id) | (Match.team2 == team_id)
            )
            .first()
        )
        if in_progress:
            return Err(
                ValidationError(
                    "Cannot deregister once your team has played in a match that is in progress."
                )
            )

        team_registration.status = RegistrationStatus.CANCELLED

        PlayerRegistration.query.filter_by(event=tournament_url, team=team_id).update(
            {"status": RegistrationStatus.CANCELLED}
        )

        db.session.commit()
        return Ok(None)

    @staticmethod
    @allow_Q
    def deregister_player(
        tournament_url: str, player_id: str
    ) -> Result[None, ArctosError]:
        from models import Match, Tournament, PlayerRegistration, db

        tournament = RegistrationService._get_tournament(tournament_url).Q()
        RegistrationService._require_player_registration_open_for_deregister(tournament).Q()

        player_registration = (
            PlayerRegistration.query.filter_by(event=tournament_url, player=player_id)
            .filter(
                PlayerRegistration.status.in_(
                    [
                        RegistrationStatus.PENDING_TEAM_APPROVAL,
                        RegistrationStatus.CONFIRMED,
                    ]
                )
            )
            .first()
        )
        if not player_registration:
            return Err(ValidationError("You are not registered for this tournament"))

        player_team = player_registration.team
        if player_team:
            in_progress = (
                Match.query.filter_by(
                    event=tournament_url, status=MatchStatus.IN_PROGRESS
                )
                .filter(
                    (Match.team1 == player_team) | (Match.team2 == player_team)
                )
                .first()
            )
            if in_progress:
                return Err(
                    ValidationError(
                        "Cannot deregister once you have played in a match that is in progress."
                    )
                )

        player_registration.status = RegistrationStatus.CANCELLED

        db.session.commit()
        return Ok(None)

    @staticmethod
    @allow_Q
    def register_team_for_league(
        league_id: str, team_id: str, pseudonym: str
    ) -> Result["TeamRegistration", ArctosError]:
        from models import TeamRegistration, League, db

        league = League.query.get(league_id)
        if not league:
            return Err(ValidationError("League not found"))
        rc = league.registrable_config
        if not (rc and getattr(rc, "team_registration_open", rc.registration_open)):
            return Err(
                RegistrationClosedError(
                    "Registration is not open for this league"
                )
            )

        pseudonym = (pseudonym or "").strip()
        if not pseudonym:
            return Err(ValidationError("Team pseudonym is required"))
        if "::" in pseudonym:
            return Err(ValidationError('Team pseudonyms cannot contain "::"'))

        existing_reg = TeamRegistration.query.filter_by(
            league_id=league_id, team=team_id, status="CONFIRMED"
        ).first()
        if existing_reg:
            return Err(
                ValidationError("Your team is already registered for this league")
            )

        n_max = getattr(rc, "n_max_teams", None) if rc else None
        if n_max is not None:
            current_team_count = TeamRegistration.query.filter_by(
                league_id=league_id,
                status=TeamRegistrationStatus.CONFIRMED,
            ).count()
            if current_team_count >= n_max:
                return Err(
                    ValidationError(
                        f"Maximum number of teams ({n_max}) already registered"
                    )
                )

        team_registration = TeamRegistration(
            event=None,
            league_id=league_id,
            team=team_id,
            pseudonym=pseudonym,
        )

        rc = league.registrable_config
        if not rc or not rc.team_reg_fee or rc.team_reg_fee == 0:
            team_registration.paid = True
            team_registration.amount_paid = 0.0
            team_registration.paid_at = datetime.now(timezone.utc).replace(tzinfo=None)

        db.session.add(team_registration)
        db.session.commit()
        return Ok(team_registration)

    @staticmethod
    @allow_Q
    def register_player_for_league(
        league_id: str,
        player_id: str,
        team_id: Optional[str],
        *,
        jersey_number: str = "",
        jersey_name: str = "",
        waiver_legal_name_signature: str = "",
    ) -> Result["PlayerRegistration", ArctosError]:
        from models import PlayerRegistration, League, db

        league = League.query.get(league_id)
        if not league:
            return Err(ValidationError("League not found"))
        rc = league.registrable_config
        if not (rc and getattr(rc, "player_registration_open", rc.registration_open)):
            return Err(
                RegistrationClosedError(
                    "Registration is not open for this league"
                )
            )

        team_id = (team_id or "").strip() or None
        status = (
            RegistrationStatus.CONFIRMED
            if not team_id
            else RegistrationStatus.PENDING_TEAM_APPROVAL
        )

        existing_reg = PlayerRegistration.query.filter_by(
            league_id=league_id, player=player_id
        ).first()

        if existing_reg:
            if existing_reg.status not in (
                RegistrationStatus.REJECTED,
                RegistrationStatus.CANCELLED,
            ):
                return Err(
                    ValidationError(
                        "You already have a registration for this league"
                    )
                )
            player_registration = existing_reg
            player_registration.team = team_id
            player_registration.jersey_number = jersey_number or ""
            player_registration.jersey_name = jersey_name or ""
            player_registration.status = status
        else:
            player_registration = PlayerRegistration(
                event=None,
                league_id=league_id,
                player=player_id,
                team=team_id,
                jersey_number=jersey_number or "",
                jersey_name=jersey_name or "",
                status=status,
            )

        rc = league.registrable_config
        if not rc or not rc.player_reg_fee or rc.player_reg_fee == 0:
            player_registration.paid = True
            player_registration.amount_paid = 0.0
            player_registration.paid_at = datetime.now(timezone.utc).replace(tzinfo=None)

        # If a waiver is configured, players must sign it.
        waiver_filepath = getattr(rc, "waiver_filepath", None) if rc else None
        if waiver_filepath:
            signature = (waiver_legal_name_signature or "").strip()
            if not signature:
                return Err(ValidationError("Waiver signature is required"))
            current_waiver_sha = getattr(rc, "waiver_sha256", None)
            if not current_waiver_sha:
                return Err(ValidationError("Waiver is missing its checksum"))

            now = datetime.now(timezone.utc).replace(tzinfo=None)
            player_registration.waiver_legal_name_signature = signature
            player_registration.waiver_legal_name_signature_sha256 = current_waiver_sha
            player_registration.waiver_signature_submitted_at = now

        db.session.add(player_registration)
        db.session.commit()
        return Ok(player_registration)

    @staticmethod
    @allow_Q
    def deregister_team_from_league(
        league_id: str, team_id: str
    ) -> Result[None, ArctosError]:
        from models import TeamRegistration, PlayerRegistration, League, db

        league = League.query.get(league_id)
        if not league:
            return Err(ValidationError("League not found"))
        rc = league.registrable_config
        if not (rc and getattr(rc, "team_registration_open", rc.registration_open)):
            return Err(
                ValidationError(
                    "Registration changes are locked for this league"
                )
            )

        team_registration = TeamRegistration.query.filter_by(
            league_id=league_id, team=team_id, status="CONFIRMED"
        ).first()
        if not team_registration:
            return Err(ValidationError("You are not registered for this league"))

        from models import Match, Tournament

        tournament_urls = [
            t.url
            for t in Tournament.query.filter_by(league_id=league_id).all()
        ]
        in_progress = (
            Match.query.filter(
                Match.event.in_(tournament_urls),
                Match.status == MatchStatus.IN_PROGRESS,
            )
            .filter((Match.team1 == team_id) | (Match.team2 == team_id))
            .first()
        )
        if in_progress:
            return Err(
                ValidationError(
                    "Cannot deregister once your team has played in a match that is in progress."
                )
            )

        team_registration.status = TeamRegistrationStatus.CANCELLED

        PlayerRegistration.query.filter_by(
            league_id=league_id, team=team_id
        ).update({"status": RegistrationStatus.CANCELLED})

        db.session.commit()
        return Ok(None)

    @staticmethod
    @allow_Q
    def deregister_player_from_league(
        league_id: str, player_id: str
    ) -> Result[None, ArctosError]:
        from models import PlayerRegistration, League, db

        league = League.query.get(league_id)
        if not league:
            return Err(ValidationError("League not found"))
        rc = league.registrable_config
        if not (rc and getattr(rc, "player_registration_open", rc.registration_open)):
            return Err(
                ValidationError(
                    "Registration changes are locked for this league"
                )
            )

        player_registration = (
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
            .first()
        )
        if not player_registration:
            return Err(
                ValidationError("You are not registered for this league")
            )

        player_team = player_registration.team
        if player_team:
            from models import Match, Tournament

            tournament_urls = [
                t.url
                for t in Tournament.query.filter_by(
                    league_id=league_id
                ).all()
            ]
            in_progress = (
                Match.query.filter(
                    Match.event.in_(tournament_urls),
                    Match.status == MatchStatus.IN_PROGRESS,
                )
                .filter(
                    (Match.team1 == player_team) | (Match.team2 == player_team)
                )
                .first()
            )
            if in_progress:
                return Err(
                    ValidationError(
                        "Cannot deregister once you have played in a match that is in progress."
                    )
                )

        player_registration.status = RegistrationStatus.CANCELLED

        db.session.commit()
        return Ok(None)
