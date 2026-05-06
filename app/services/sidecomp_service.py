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
    NotFoundError,
    RegistrationClosedError,
    UnauthorizedError,
    ValidationError,
)

if TYPE_CHECKING:  # pragma: no cover
    from app.domain.enums import SideCompType
    from models import SideComp, SideCompRegistration, Tournament


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
    def _next_entry_number(comp_id: int) -> int:
        """Return the next 1-indexed ``entry_number`` for *comp_id*.

        Returns one more than the current max ``entry_number`` for the comp,
        or ``1`` if the comp has no registrations. Numbers are not reused
        when a registrant is removed.
        """
        from sqlalchemy import func

        from models import SideCompRegistration, db

        current_max = (
            db.session.query(func.max(SideCompRegistration.entry_number)).filter_by(comp=comp_id).scalar()
        )
        return (current_max or 0) + 1

    @staticmethod
    def _require_to(tournament_url: str, actor_user_id: str, actor_user_type: str) -> Result[None, ArctosError]:
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
        description: Optional[str] = None,
    ) -> Result["SideComp", ArctosError]:
        """Create a new side competition for *tournament_url*.

        Args:
            tournament_url: URL slug of the parent tournament.
            actor_user_id: ID of the user attempting the create. Must be a TO.
            actor_user_type: ``"player"`` or ``"team"``.
            name: Display name of the side competition. Must be non-blank.
            type: One of the :class:`~app.domain.enums.SideCompType` values.
            description: Optional free-form description. Empty/whitespace
                strings are treated as ``None``.

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

        description_value: Optional[str] = None
        if description is not None:
            stripped = description.strip()
            description_value = stripped if stripped else None

        sc = SideComp(
            event=tournament_url,
            name=name_value,
            type=parsed_type,
            description=description_value,
        )
        db.session.add(sc)
        db.session.commit()
        return Ok(sc)

    @staticmethod
    def list_for_event(tournament_url: str):
        """Return all side competitions for *tournament_url*, oldest first.

        Args:
            tournament_url: URL slug of the parent tournament.

        Returns:
            List of :class:`~app.models.sidecomp.SideComp` rows ordered by
            ``created_at`` ascending. Empty list if there are none.
        """
        from models import SideComp

        return SideComp.query.filter_by(event=tournament_url).order_by(SideComp.created_at.asc()).all()

    @staticmethod
    def get_with_registrants(comp_id: int) -> Result[tuple, ArctosError]:
        """Return a side competition and its registrants by *comp_id*.

        Args:
            comp_id: Primary key of the :class:`~app.models.sidecomp.SideComp`.

        Returns:
            :class:`~app.error_values.Ok` wrapping
            ``(SideComp, list[(SideCompRegistration, Player)])`` ordered by
            registration time, or :class:`~app.error_values.Err` with a
            :class:`~app.exceptions.NotFoundError` if the comp does not exist.
        """
        from models import Player, SideComp, SideCompRegistration

        sc = SideComp.query.get(comp_id)
        if sc is None:
            return Err(NotFoundError("Side competition not found"))

        rows = (
            SideCompRegistration.query.filter_by(comp=comp_id).order_by(SideCompRegistration.registered_at.asc()).all()
        )
        registrants = []
        for r in rows:
            p = Player.query.get(r.player)
            registrants.append((r, p))
        return Ok((sc, registrants))

    @staticmethod
    @allow_Q
    def update(
        comp_id: int,
        *,
        actor_user_id: str,
        actor_user_type: str,
        name: Optional[str] = None,
        type: Optional[str] = None,
        description: Optional[str] = None,
        registration_open: Optional[bool] = None,
    ) -> Result["SideComp", ArctosError]:
        """Update fields of an existing side competition.

        Args:
            comp_id: Primary key of the :class:`~app.models.sidecomp.SideComp`.
            actor_user_id: ID of the user attempting the update. Must be a TO.
            actor_user_type: ``"player"`` or ``"team"``.
            name: New display name. If ``None``, the field is left untouched.
                Must be non-blank when provided.
            type: New :class:`~app.domain.enums.SideCompType` value. If ``None``,
                the field is left untouched.
            description: New description. If ``None``, the field is left
                untouched. An empty/whitespace string clears it to ``None``.
            registration_open: New value for the registration-open gate. If
                ``None``, the field is left untouched.

        Returns:
            :class:`~app.error_values.Ok` wrapping the updated
            :class:`~app.models.sidecomp.SideComp`, or an
            :class:`~app.error_values.Err` describing the failure (comp not
            found, actor not a TO, invalid name, or invalid type).
        """
        from models import SideComp, db

        sc = SideComp.query.get(comp_id)
        if sc is None:
            return Err(NotFoundError("Side competition not found"))

        SideCompService._require_to(sc.event, actor_user_id, actor_user_type).Q()

        if name is not None:
            name_value = name.strip()
            if not name_value:
                return Err(ValidationError("Side competition name is required"))
            sc.name = name_value

        if type is not None:
            parsed_type = _parse_type(type)
            if parsed_type is None:
                return Err(ValidationError("Invalid side competition type"))
            sc.type = parsed_type

        if description is not None:
            stripped = description.strip()
            sc.description = stripped if stripped else None

        if registration_open is not None:
            sc.registration_open = bool(registration_open)

        db.session.commit()
        return Ok(sc)

    @staticmethod
    @allow_Q
    def delete(
        comp_id: int,
        *,
        actor_user_id: str,
        actor_user_type: str,
    ) -> Result[None, ArctosError]:
        """Delete a side competition along with its registrations and results.

        Args:
            comp_id: Primary key of the :class:`~app.models.sidecomp.SideComp`.
            actor_user_id: ID of the user attempting the delete. Must be a TO.
            actor_user_type: ``"player"`` or ``"team"``.

        Returns:
            :class:`~app.error_values.Ok` wrapping ``None`` on success, or an
            :class:`~app.error_values.Err` describing the failure (comp not
            found or actor not a TO).
        """
        from models import SideComp, SideCompRegistration, SideCompResult, db

        sc = SideComp.query.get(comp_id)
        if sc is None:
            return Err(NotFoundError("Side competition not found"))

        SideCompService._require_to(sc.event, actor_user_id, actor_user_type).Q()

        SideCompRegistration.query.filter_by(comp=comp_id).delete(synchronize_session=False)
        SideCompResult.query.filter_by(comp=comp_id).delete(synchronize_session=False)
        db.session.delete(sc)
        db.session.commit()
        return Ok(None)

    @staticmethod
    @allow_Q
    def register_player(
        comp_id: int,
        *,
        player_id: str,
    ) -> Result["SideCompRegistration", ArctosError]:
        """Register *player_id* for side competition *comp_id* (self-registration).

        Args:
            comp_id: Primary key of the :class:`~app.models.sidecomp.SideComp`.
            player_id: ID of the player registering themselves.

        Returns:
            :class:`~app.error_values.Ok` wrapping the persisted
            :class:`~app.models.sidecomp.SideCompRegistration`, or an
            :class:`~app.error_values.Err` describing the failure (comp not
            found, player not registered for the parent event, or duplicate
            registration).
        """
        from app.domain.enums import RegistrationStatus
        from models import (
            PlayerRegistration,
            SideComp,
            SideCompRegistration,
            db,
        )

        sc = SideComp.query.get(comp_id)
        if sc is None:
            return Err(NotFoundError("Side competition not found"))

        if not sc.registration_open:
            return Err(RegistrationClosedError("This side competition is not open for registration"))

        event_reg = PlayerRegistration.query.filter_by(
            event=sc.event,
            player=player_id,
            status=RegistrationStatus.CONFIRMED,
        ).first()
        if not event_reg:
            return Err(ValidationError("You must be registered for the event before joining a side competition"))

        existing = SideCompRegistration.query.filter_by(comp=comp_id, player=player_id).first()
        if existing:
            return Err(ValidationError("You are already registered for this side competition"))

        entry_number = SideCompService._next_entry_number(comp_id)
        reg = SideCompRegistration(
            comp=comp_id,
            player=player_id,
            entry_number=entry_number,
            registered_by_to=False,
        )
        db.session.add(reg)
        db.session.commit()
        return Ok(reg)

    @staticmethod
    @allow_Q
    def organizer_check_in(
        comp_id: int,
        *,
        actor_user_id: str,
        actor_user_type: str,
        player_id: str,
    ) -> Result["SideCompRegistration", ArctosError]:
        """Register *player_id* for side competition *comp_id* on behalf of a TO.

        The resulting :class:`~app.models.sidecomp.SideCompRegistration` row has
        ``registered_by_to=True`` so it is distinguishable from a player's
        self-registration.

        Args:
            comp_id: Primary key of the :class:`~app.models.sidecomp.SideComp`.
            actor_user_id: ID of the user performing the check-in. Must be a TO
                of the parent event.
            actor_user_type: ``"player"`` or ``"team"``.
            player_id: ID of the player being checked in.

        Returns:
            :class:`~app.error_values.Ok` wrapping the persisted
            :class:`~app.models.sidecomp.SideCompRegistration`, or an
            :class:`~app.error_values.Err` describing the failure (comp not
            found, actor not a TO, target player not found, target not
            registered for the parent event, or duplicate registration).
        """
        from app.domain.enums import RegistrationStatus
        from models import (
            Player,
            PlayerRegistration,
            SideComp,
            SideCompRegistration,
            db,
        )

        sc = SideComp.query.get(comp_id)
        if sc is None:
            return Err(NotFoundError("Side competition not found"))

        SideCompService._require_to(sc.event, actor_user_id, actor_user_type).Q()

        target = Player.query.get(player_id)
        if target is None:
            return Err(ValidationError("Player not found"))

        event_reg = PlayerRegistration.query.filter_by(
            event=sc.event,
            player=player_id,
            status=RegistrationStatus.CONFIRMED,
        ).first()
        if not event_reg:
            return Err(ValidationError("Player is not registered for this event"))

        existing = SideCompRegistration.query.filter_by(comp=comp_id, player=player_id).first()
        if existing:
            return Err(ValidationError("Player is already registered for this side competition"))

        entry_number = SideCompService._next_entry_number(comp_id)
        reg = SideCompRegistration(
            comp=comp_id,
            player=player_id,
            entry_number=entry_number,
            registered_by_to=True,
        )
        db.session.add(reg)
        db.session.commit()
        return Ok(reg)

    @staticmethod
    @allow_Q
    def organizer_remove(
        comp_id: int,
        *,
        actor_user_id: str,
        actor_user_type: str,
        player_id: str,
    ) -> Result[None, ArctosError]:
        """Remove *player_id*'s side-competition registration on behalf of a TO.

        Idempotent: removing a row that doesn't exist returns
        :class:`~app.error_values.Ok`.

        Args:
            comp_id: Primary key of the :class:`~app.models.sidecomp.SideComp`.
            actor_user_id: ID of the user performing the removal. Must be a TO
                of the parent event.
            actor_user_type: ``"player"`` or ``"team"``.
            player_id: ID of the player being removed.

        Returns:
            :class:`~app.error_values.Ok` wrapping ``None`` on success, or an
            :class:`~app.error_values.Err` describing the failure (comp not
            found or actor not a TO).
        """
        from models import SideComp, SideCompRegistration, db

        sc = SideComp.query.get(comp_id)
        if sc is None:
            return Err(NotFoundError("Side competition not found"))

        SideCompService._require_to(sc.event, actor_user_id, actor_user_type).Q()

        SideCompRegistration.query.filter_by(comp=comp_id, player=player_id).delete(synchronize_session=False)
        db.session.commit()
        return Ok(None)

    @staticmethod
    def cancel_player_registrations_in_event(event: str, player: str) -> None:
        """Hard-delete all SideCompRegistration rows for ``(event, player)``.

        Called by RegistrationService when a player's event registration is
        cancelled. No Result wrapper - the caller is already inside a
        transaction.
        """
        from models import SideComp, SideCompRegistration

        comp_ids = [c.id for c in SideComp.query.filter_by(event=event).all()]
        if not comp_ids:
            return
        SideCompRegistration.query.filter(
            SideCompRegistration.comp.in_(comp_ids),
            SideCompRegistration.player == player,
        ).delete(synchronize_session=False)

    @staticmethod
    @allow_Q
    def deregister_player(
        comp_id: int,
        *,
        player_id: str,
    ) -> Result[None, ArctosError]:
        """Remove *player_id*'s registration for side competition *comp_id*.

        Idempotent: removing a row that doesn't exist returns
        :class:`~app.error_values.Ok`.

        Args:
            comp_id: Primary key of the :class:`~app.models.sidecomp.SideComp`.
            player_id: ID of the player deregistering themselves.

        Returns:
            :class:`~app.error_values.Ok` wrapping ``None`` on success, or an
            :class:`~app.error_values.Err` with a
            :class:`~app.exceptions.NotFoundError` if the comp does not exist.
        """
        from models import SideComp, SideCompRegistration, db

        sc = SideComp.query.get(comp_id)
        if sc is None:
            return Err(NotFoundError("Side competition not found"))

        SideCompRegistration.query.filter_by(comp=comp_id, player=player_id).delete(synchronize_session=False)
        db.session.commit()
        return Ok(None)
