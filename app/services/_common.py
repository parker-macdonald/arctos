"""Shared service-layer helpers.

Tiny, dependency-light functions reused by multiple services.
Anything more domain-specific should live in its own service module.
"""

from __future__ import annotations

from app.error_values import Err, Ok, Result
from app.exceptions import ArctosError


def get_tournament_or_err(tournament_url: str) -> "Result":
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
        return Err(
            ArctosError("Tournament not found", status_code=404, public=True)
        )
    return Ok(tournament)
