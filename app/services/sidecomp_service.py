"""Side competition service.

Encapsulates side-competition CRUD, player self-registration, and TO-driven
check-in. Mirrors the style of :class:`~app.services.registration_service.RegistrationService`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from app.error_values import Err, Ok, Result, allow_Q, option
from app.exceptions import (
    ArctosError,
    UnauthorizedError,
    ValidationError,
)

if TYPE_CHECKING:  # pragma: no cover
    from app.domain.enums import SideCompType
    from models import SideComp, Tournament


def _parse_type(value: object) -> Optional["SideCompType"]:
    """Parse *value* into a :class:`~app.domain.enums.SideCompType` member.

    Returns ``None`` if *value* is not a valid side competition type.
    """
    from app.domain.enums import SideCompType

    if value is None:
        return None
    if isinstance(value, SideCompType):
        return value
    try:
        return SideCompType(str(value))
    except ValueError:
        return None


@dataclass(frozen=True)
class SideCompService:
    """Side competition workflows. Static methods, namespace dataclass."""

    @staticmethod
    def _get_tournament(tournament_url: str) -> Result["Tournament", ArctosError]:
        from app.exceptions import TournamentNotFoundError
        from models import Tournament

        tournament = Tournament.query.filter_by(url=tournament_url).first()
        return option(tournament).ok_or(TournamentNotFoundError(tournament_url))

    @staticmethod
    def _require_to(
        tournament_url: str, actor_user_id: str, actor_user_type: str
    ) -> Result[None, ArctosError]:
        from models import TO

        is_to = TO.query.filter_by(
            event=tournament_url,
            user_id=actor_user_id,
            user_type=actor_user_type,
        ).first()
        if not is_to:
            return Err(UnauthorizedError("Only tournament organizers can do that"))
        return Ok(None)

    @staticmethod
    @allow_Q
    def create(
        tournament_url: str,
        *,
        actor_user_id: str,
        actor_user_type: str,
        name: str,
        type: str,
    ) -> Result["SideComp", ArctosError]:
        """Create a new side competition for *tournament_url*.

        Args:
            tournament_url: URL slug of the parent tournament.
            actor_user_id: ID of the user attempting the create. Must be a TO.
            actor_user_type: ``"player"`` or ``"team"``.
            name: Display name of the side competition. Must be non-blank.
            type: One of the :class:`~app.domain.enums.SideCompType` values.

        Returns:
            :class:`~app.error_values.Ok` wrapping the persisted
            :class:`~app.models.sidecomp.SideComp`, or an :class:`~app.error_values.Err`
            describing the failure (tournament not found, actor not a TO,
            invalid name, or invalid type).
        """
        from models import SideComp, db

        SideCompService._get_tournament(tournament_url).Q()
        SideCompService._require_to(tournament_url, actor_user_id, actor_user_type).Q()

        name_value = (name or "").strip()
        if not name_value:
            return Err(ValidationError("Side competition name is required"))

        parsed_type = _parse_type(type)
        if parsed_type is None:
            return Err(ValidationError("Invalid side competition type"))

        sc = SideComp(event=tournament_url, name=name_value, type=parsed_type)
        db.session.add(sc)
        db.session.commit()
        return Ok(sc)
