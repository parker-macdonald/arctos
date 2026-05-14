"""Shared service-layer helpers.

Tiny, dependency-light functions reused by multiple services.
Anything more domain-specific should live in its own service module.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.error_values import Err, Ok, Result
from app.exceptions import ArctosError


def get_tournament_or_err(tournament_url: str) -> Result["Tournament", ArctosError]:
    """Return ``Ok(Tournament)`` for *tournament_url* or a 404 ``Err``.

    Args:
        tournament_url: URL slug of the tournament.

    Returns:
        ``Ok(tournament)`` when found; otherwise
        ``Err(ArctosError("Tournament not found", status_code=404, public=True))``.
    """
    from models import Tournament

    tournament = Tournament.query.filter_by(url=tournament_url).first()
    if tournament is None:
        return Err(ArctosError("Tournament not found", status_code=404, public=True))
    return Ok(tournament)


def resolve_actor(actor_user_id: str, actor_user_type: str):
    """Load a :class:`~app.models.Player` or :class:`~app.models.Team` by id+type.

    Args:
        actor_user_id: Primary key of the actor.
        actor_user_type: ``"player"`` or ``"team"`` (matches
            :class:`~app.domain.enums.UserType` member values).

    Returns:
        The Player/Team instance, or ``None`` if the type is unknown or the
        record doesn't exist. Service code that needs a user object for
        :meth:`~app.services.permission_service.PermissionService.is_tournament_organizer`
        can pass the result directly; the underlying check returns ``False``
        for ``None`` users.
    """
    from app.domain.enums import UserType
    from models import Player, Team

    if actor_user_type == UserType.PLAYER.value:
        return Player.query.get(actor_user_id)
    if actor_user_type == UserType.TEAM.value:
        return Team.query.get(actor_user_id)
    return None


def current_user_type() -> str:
    """Return the current_user's account type as a bare string.

    Assumes the request is guarded by ``@login_required`` and ``current_user``
    is a :class:`~app.models.player.Player` or
    :class:`~app.models.team.Team`. Raises a clear error otherwise so a
    misconfigured route surfaces fast rather than silently misbehaving.

    Returns:
        ``"player"`` or ``"team"`` (matches
        :class:`~app.domain.enums.UserType` member values).
    """
    from flask_login import current_user
    from app.error_values import Some
    from app.services.permission_service import PermissionService

    match PermissionService.user_type(current_user):
        case Some(user_type):
            return str(user_type)
        case _:
            raise RuntimeError(
                "current_user_type() called without an authenticated Player/Team; is @login_required missing?"
            )


@dataclass(frozen=True)
class Scope:
    """Identifies a registration / manage context as either an event or league.

    Use the factory methods (:meth:`event`, :meth:`league`) to construct
    instances; they enforce the mutual-exclusion invariant and produce
    immutable values that can be threaded through the service layer without
    mutation hazards.

    Attributes:
        event_url: URL slug of a standalone tournament, or ``None``.
        league_url: URL slug of a league, or ``None``.
    """

    event_url: str | None = None
    league_url: str | None = None

    @classmethod
    def event(cls, url: str) -> "Scope":
        """Build a Scope referring to a standalone tournament."""
        return cls(event_url=url)

    @classmethod
    def league(cls, url: str) -> "Scope":
        """Build a Scope referring to a league."""
        return cls(league_url=url)

    @property
    def is_event(self) -> bool:
        return self.event_url is not None

    @property
    def is_league(self) -> bool:
        return self.league_url is not None

    @property
    def url(self) -> str:
        """Return whichever URL is set.

        Always returns a non-None string; the ``__post_init__`` invariant
        guarantees exactly one of ``event_url`` / ``league_url`` is set.
        """
        if self.event_url is not None:
            return self.event_url
        assert self.league_url is not None  # invariant guarantees this
        return self.league_url

    def __post_init__(self) -> None:
        # Block direct constructor misuse - exactly one URL must be set.
        if (self.event_url is None) == (self.league_url is None):
            raise ValueError("Scope must have exactly one of event_url or league_url set")
