"""Side competition service.

Encapsulates side-competition CRUD, player self-registration, and TO-driven
registration. Mirrors the style of :class:`~app.services.registration_service.RegistrationService`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from app.error_values import Err, Ok, Result, allow_Q
from app.exceptions import (
    ArctosError,
    NotFoundError,
    RegistrationClosedError,
    UnauthorizedError,
    ValidationError,
)
from app.models.constants import SHORT_NAME_LEN

if TYPE_CHECKING:  # pragma: no cover
    from app.domain.enums import SideCompType
    from models import SideComp, SideCompCategory, SideCompRegistration, Tournament


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
        from app.services._common import get_tournament_or_err

        return get_tournament_or_err(tournament_url)

    @staticmethod
    def _assign_entry_number(tournament_url: str, player_id: str) -> int:
        """Return *player_id*'s entry number for *tournament_url*, assigning one
        if this is their first side competition in the tournament.

        The number is scoped to the tournament, not the individual side
        competition, so a player carries the same number across every side
        competition they enter. The first assignment takes one more than the
        current max for the tournament; numbers are not reused after a
        deregistration. Retries once on IntegrityError to absorb a concurrent
        first-time assignment for two players
        (uq_sidecomp_entry_numbers_tournament_entry_number).
        """
        from sqlalchemy.exc import IntegrityError

        from models import SideCompEntryNumber, db

        last_exc: Exception | None = None
        for _ in range(2):
            existing = SideCompEntryNumber.query.filter_by(tournament_url=tournament_url, player=player_id).first()
            if existing:
                return existing.entry_number

            row = SideCompEntryNumber(
                tournament_url=tournament_url,
                player=player_id,
                entry_number=SideCompService._next_tournament_entry_number(tournament_url),
            )
            db.session.add(row)
            try:
                db.session.commit()
                return row.entry_number
            except IntegrityError as exc:
                db.session.rollback()
                last_exc = exc
                continue
        assert last_exc is not None
        raise last_exc

    @staticmethod
    def _next_tournament_entry_number(tournament_url: str) -> int:
        """Return one more than the current max entry number in *tournament_url*."""
        from sqlalchemy import func

        from models import SideCompEntryNumber, db

        current_max = (
            db.session.query(func.max(SideCompEntryNumber.entry_number))
            .filter_by(tournament_url=tournament_url)
            .scalar()
        )
        return (current_max or 0) + 1

    @staticmethod
    def entry_number_for(tournament_url: str, player_id: str) -> Optional[int]:
        """Return *player_id*'s tournament entry number, or ``None`` if unassigned."""
        from models import SideCompEntryNumber

        row = SideCompEntryNumber.query.filter_by(tournament_url=tournament_url, player=player_id).first()
        return row.entry_number if row else None

    @staticmethod
    def entry_numbers_for_tournament(tournament_url: str) -> dict[str, int]:
        """Return a ``{player_id: entry_number}`` map for *tournament_url*."""
        from models import SideCompEntryNumber

        return {
            row.player: row.entry_number
            for row in SideCompEntryNumber.query.filter_by(tournament_url=tournament_url).all()
        }

    @staticmethod
    def _insert_registration(
        *,
        tournament_url: str,
        comp_id: int,
        player_id: str,
        registered_by_to: bool,
        category_id: Optional[int] = None,
    ) -> "SideCompRegistration":
        """Insert a SideCompRegistration, ensuring the player has a tournament
        entry number first. Caller is responsible for any pre-insert validation.
        """
        from models import SideCompRegistration, db

        SideCompService._assign_entry_number(tournament_url, player_id)
        reg = SideCompRegistration(
            comp=comp_id,
            player=player_id,
            category=category_id,
            registered_by_to=registered_by_to,
        )
        db.session.add(reg)
        db.session.commit()
        return reg

    @staticmethod
    def _require_to(tournament_url: str, actor_user_id: str, actor_user_type: str) -> Result[None, ArctosError]:
        from app.services._common import resolve_actor
        from app.services.permission_service import PermissionService

        actor = resolve_actor(actor_user_id, actor_user_type)
        if not PermissionService.is_tournament_organizer(tournament_url, actor):
            return Err(UnauthorizedError("Only tournament organizers can do that"))
        return Ok(None)

    @staticmethod
    def _confirmed_player_registration_for_tournament(tournament_url: str, player_id: str):
        from app.domain.enums import RegistrationStatus
        from app.services.registration_resolver import player_registrations_for_tournament
        from models import Tournament

        tournament = Tournament.query.get(tournament_url)
        if tournament is None:
            return None

        registrations = player_registrations_for_tournament(tournament, statuses=[RegistrationStatus.CONFIRMED])
        for registration in registrations:
            if registration.player == player_id:
                return registration
        return None

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
        categories: Optional[list[str]] = None,
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
            categories: Optional list of category names to create alongside the
                comp. Blank entries are dropped; duplicates are rejected.

        Returns:
            :class:`~app.error_values.Ok` wrapping the persisted
            :class:`~app.models.sidecomp.SideComp`, or an :class:`~app.error_values.Err`
            describing the failure (tournament not found, actor not a TO,
            invalid name, invalid type, or duplicate category names).
        """
        from sqlalchemy.exc import IntegrityError

        from models import SideComp, SideCompCategory, db

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

        category_names = [n.strip() for n in (categories or []) if n and n.strip()]
        if len(set(category_names)) != len(category_names):
            return Err(ValidationError("Duplicate category names"))

        sc = SideComp(
            event=tournament_url,
            name=name_value,
            type=parsed_type,
            description=description_value,
        )
        db.session.add(sc)
        db.session.flush()
        for category_name in category_names:
            db.session.add(SideCompCategory(comp=sc.id, name=category_name))
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return Err(ValidationError("Duplicate category names"))
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
        player_ids = [r.player for r in rows]
        players_by_id = {p.id: p for p in Player.query.filter(Player.id.in_(player_ids)).all()} if player_ids else {}
        registrants = [(r, players_by_id.get(r.player)) for r in rows]
        return Ok((sc, registrants))

    @staticmethod
    def list_categories(comp_id: int) -> Result[list, ArctosError]:
        """Return a side competition's categories, oldest first.

        Returns :class:`~app.error_values.Err` with a
        :class:`~app.exceptions.NotFoundError` if the comp does not exist.
        """
        from models import SideComp, SideCompCategory

        sc = SideComp.query.get(comp_id)
        if sc is None:
            return Err(NotFoundError("Side competition not found"))

        cats = (
            SideCompCategory.query.filter_by(comp=comp_id)
            .order_by(SideCompCategory.created_at.asc(), SideCompCategory.id.asc())
            .all()
        )
        return Ok(cats)

    @staticmethod
    @allow_Q
    def create_category(
        comp_id: int,
        *,
        actor_user_id: str,
        actor_user_type: str,
        name: str,
    ) -> Result["SideCompCategory", ArctosError]:
        """Create a category under side competition *comp_id* (TO only)."""
        from sqlalchemy.exc import IntegrityError

        from models import SideComp, SideCompCategory, db

        sc = SideComp.query.get(comp_id)
        if sc is None:
            return Err(NotFoundError("Side competition not found"))

        SideCompService._require_to(sc.event, actor_user_id, actor_user_type).Q()

        name_value = (name or "").strip()
        if not name_value:
            return Err(ValidationError("Category name is required"))
        if len(name_value) > SHORT_NAME_LEN:
            return Err(ValidationError("Category name is too long"))

        if SideCompCategory.query.filter_by(comp=comp_id, name=name_value).first():
            return Err(ValidationError("A category with that name already exists"))

        cat = SideCompCategory(comp=comp_id, name=name_value)
        db.session.add(cat)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return Err(ValidationError("A category with that name already exists"))
        return Ok(cat)

    @staticmethod
    @allow_Q
    def rename_category(
        category_id: int,
        *,
        actor_user_id: str,
        actor_user_type: str,
        name: str,
    ) -> Result["SideCompCategory", ArctosError]:
        """Rename a category (TO only)."""
        from sqlalchemy.exc import IntegrityError

        from models import SideComp, SideCompCategory, db

        cat = SideCompCategory.query.get(category_id)
        if cat is None:
            return Err(NotFoundError("Category not found"))

        sc = SideComp.query.get(cat.comp)
        SideCompService._require_to(sc.event, actor_user_id, actor_user_type).Q()

        name_value = (name or "").strip()
        if not name_value:
            return Err(ValidationError("Category name is required"))
        if len(name_value) > SHORT_NAME_LEN:
            return Err(ValidationError("Category name is too long"))

        collision = (
            SideCompCategory.query.filter_by(comp=cat.comp, name=name_value)
            .filter(SideCompCategory.id != category_id)
            .first()
        )
        if collision:
            return Err(ValidationError("A category with that name already exists"))

        cat.name = name_value
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return Err(ValidationError("A category with that name already exists"))
        return Ok(cat)

    @staticmethod
    @allow_Q
    def delete_category(
        category_id: int,
        *,
        actor_user_id: str,
        actor_user_type: str,
        mode: Optional[str] = None,
        target_category_id: Optional[int] = None,
    ) -> Result[None, ArctosError]:
        """Delete a category, resolving any players registered under it (TO only).

        If the category has no registered players, it is deleted directly and
        *mode* is ignored. Otherwise *mode* must be:

        * ``"deregister"`` — remove the affected players from the side
          competition (their tournament entry numbers are not reused).
        * ``"move"`` — reassign the affected players to *target_category_id*,
          which must be another category of the same comp.
        """
        from sqlalchemy.exc import IntegrityError

        from models import SideComp, SideCompCategory, SideCompRegistration, db

        cat = SideCompCategory.query.get(category_id)
        if cat is None:
            return Err(NotFoundError("Category not found"))

        sc = SideComp.query.get(cat.comp)
        SideCompService._require_to(sc.event, actor_user_id, actor_user_type).Q()

        affected = SideCompRegistration.query.filter_by(comp=cat.comp, category=category_id)

        if affected.count() == 0:
            db.session.delete(cat)
            db.session.commit()
            return Ok(None)

        if mode not in ("deregister", "move"):
            return Err(ValidationError("A resolution mode is required for a category with registered players"))

        if mode == "move":
            if target_category_id is None:
                return Err(ValidationError("Target category is required to move players"))
            if target_category_id == category_id:
                return Err(ValidationError("Cannot move players into the category being deleted"))
            target = SideCompCategory.query.get(target_category_id)
            if target is None:
                return Err(ValidationError("Target category not found"))
            if target.comp != cat.comp:
                return Err(ValidationError("Target category belongs to a different side competition"))
            affected.update({"category": target_category_id}, synchronize_session=False)
        else:
            affected.delete(synchronize_session=False)

        db.session.delete(cat)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return Err(ValidationError("Could not delete the category"))
        return Ok(None)

    @staticmethod
    def _resolve_registration_category(comp_id: int, category_id: Optional[int]) -> Result[Optional[int], ArctosError]:
        """Validate *category_id* against *comp_id*'s categories.

        Returns ``Ok(None)`` when the comp has no categories (the passed value is
        ignored), ``Ok(category_id)`` when valid, or ``Err`` when a category is
        required but missing/invalid.
        """
        from models import SideCompCategory

        cats = SideCompCategory.query.filter_by(comp=comp_id).all()
        if not cats:
            return Ok(None)
        if category_id is None:
            return Err(ValidationError("You must choose a category"))
        if category_id not in {c.id for c in cats}:
            return Err(ValidationError("Invalid category for this side competition"))
        return Ok(category_id)

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
        from models import SideComp, SideCompCategory, SideCompRegistration, SideCompResult, db

        sc = SideComp.query.get(comp_id)
        if sc is None:
            return Err(NotFoundError("Side competition not found"))

        SideCompService._require_to(sc.event, actor_user_id, actor_user_type).Q()

        SideCompRegistration.query.filter_by(comp=comp_id).delete(synchronize_session=False)
        SideCompResult.query.filter_by(comp=comp_id).delete(synchronize_session=False)
        SideCompCategory.query.filter_by(comp=comp_id).delete(synchronize_session=False)
        db.session.delete(sc)
        db.session.commit()
        return Ok(None)

    @staticmethod
    @allow_Q
    def register_player(
        comp_id: int,
        *,
        player_id: str,
        category_id: Optional[int] = None,
    ) -> Result["SideCompRegistration", ArctosError]:
        """Register *player_id* for side competition *comp_id* (self-registration).

        Args:
            comp_id: Primary key of the :class:`~app.models.sidecomp.SideComp`.
            player_id: ID of the player registering themselves.
            category_id: Chosen category. Required when the comp has categories,
                ignored when it has none.

        Returns:
            :class:`~app.error_values.Ok` wrapping the persisted
            :class:`~app.models.sidecomp.SideCompRegistration`, or an
            :class:`~app.error_values.Err` describing the failure (comp not
            found, player not registered for the parent event, missing/invalid
            category, or duplicate registration).
        """
        from models import (
            SideComp,
            SideCompRegistration,
        )

        sc = SideComp.query.get(comp_id)
        if sc is None:
            return Err(NotFoundError("Side competition not found"))

        if not sc.registration_open:
            return Err(RegistrationClosedError("This side competition is not open for registration"))

        event_reg = SideCompService._confirmed_player_registration_for_tournament(sc.event, player_id)
        if not event_reg:
            return Err(ValidationError("You must be registered for the event before joining a side competition"))

        existing = SideCompRegistration.query.filter_by(comp=comp_id, player=player_id).first()
        if existing:
            return Err(ValidationError("You are already registered for this side competition"))

        resolved_category = SideCompService._resolve_registration_category(comp_id, category_id).Q()

        reg = SideCompService._insert_registration(
            tournament_url=sc.event,
            comp_id=comp_id,
            player_id=player_id,
            registered_by_to=False,
            category_id=resolved_category,
        )
        return Ok(reg)

    @staticmethod
    @allow_Q
    def register_player_as_to(
        comp_id: int,
        *,
        actor_user_id: str,
        actor_user_type: str,
        player_id: str,
        category_id: Optional[int] = None,
    ) -> Result["SideCompRegistration", ArctosError]:
        """Register *player_id* for side competition *comp_id* via TO-driven registration.

        The resulting :class:`~app.models.sidecomp.SideCompRegistration` row has
        ``registered_by_to=True`` so it is distinguishable from a player's
        self-registration.

        Args:
            comp_id: Primary key of the :class:`~app.models.sidecomp.SideComp`.
            actor_user_id: ID of the TO registering on behalf of the player.
                Must be a TO of the parent event.
            actor_user_type: ``"player"`` or ``"team"``.
            player_id: ID of the player being registered on their behalf.
            category_id: Chosen category. Required when the comp has categories,
                ignored when it has none.

        Returns:
            :class:`~app.error_values.Ok` wrapping the persisted
            :class:`~app.models.sidecomp.SideCompRegistration`, or an
            :class:`~app.error_values.Err` describing the failure (comp not
            found, actor not a TO, target player not found, target not
            registered for the parent event, missing/invalid category, or
            duplicate registration).
        """
        from models import (
            Player,
            SideComp,
            SideCompRegistration,
        )

        sc = SideComp.query.get(comp_id)
        if sc is None:
            return Err(NotFoundError("Side competition not found"))

        SideCompService._require_to(sc.event, actor_user_id, actor_user_type).Q()

        target = Player.query.get(player_id)
        if target is None:
            return Err(ValidationError("Player not found"))

        event_reg = SideCompService._confirmed_player_registration_for_tournament(sc.event, player_id)
        if not event_reg:
            return Err(ValidationError("Player is not registered for this event"))

        existing = SideCompRegistration.query.filter_by(comp=comp_id, player=player_id).first()
        if existing:
            return Err(ValidationError("Player is already registered for this side competition"))

        resolved_category = SideCompService._resolve_registration_category(comp_id, category_id).Q()

        reg = SideCompService._insert_registration(
            tournament_url=sc.event,
            comp_id=comp_id,
            player_id=player_id,
            registered_by_to=True,
            category_id=resolved_category,
        )
        return Ok(reg)

    @staticmethod
    @allow_Q
    def deregister_player_as_to(
        comp_id: int,
        *,
        actor_user_id: str,
        actor_user_type: str,
        player_id: str,
    ) -> Result[None, ArctosError]:
        """Deregister *player_id* from side competition *comp_id* via TO-driven registration.

        Idempotent: removing a row that doesn't exist returns
        :class:`~app.error_values.Ok`.

        Args:
            comp_id: Primary key of the :class:`~app.models.sidecomp.SideComp`.
            actor_user_id: ID of the TO deregistering on behalf of the player.
                Must be a TO of the parent event.
            actor_user_type: ``"player"`` or ``"team"``.
            player_id: ID of the player being deregistered on their behalf.

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
    def cancel_players_in_event(event: str, player_ids: list[str]) -> int:
        """Bulk-cancel side-comp registrations for *player_ids* in *event*.

        Issues at most two SQL statements: one to enumerate side-comp IDs for
        the event, and one ``DELETE WHERE comp IN (...) AND player IN (...)``.
        Use this in place of looping over :meth:`cancel_player_registrations_in_event`
        when cancelling many players at once.

        No transaction commit - the caller is responsible for committing or
        rolling back as part of its own transaction.

        Args:
            event: URL slug of the parent tournament.
            player_ids: List of player IDs to cancel.

        Returns:
            Number of deleted rows.
        """
        from models import SideComp, SideCompRegistration

        if not player_ids:
            return 0
        comp_ids = [c.id for c in SideComp.query.filter_by(event=event).all()]
        if not comp_ids:
            return 0
        return (
            SideCompRegistration.query.filter(SideCompRegistration.comp.in_(comp_ids))
            .filter(SideCompRegistration.player.in_(player_ids))
            .delete(synchronize_session=False)
        )

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
