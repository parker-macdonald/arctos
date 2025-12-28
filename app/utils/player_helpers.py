"""
Player-related helper utilities.

Keep these helpers free of Flask request/session globals so they can be reused in
services, serializers, and routes.
"""

from __future__ import annotations

from typing import Optional, Tuple


def format_jersey_display(
    *,
    jersey_name: Optional[str],
    jersey_number: Optional[str],
    fallback: str,
) -> str:
    """
    Format a tournament display string based on jersey info.
    """
    jn = (jersey_name or "").strip()
    jnum = (jersey_number or "").strip()
    if jn and jnum:
        return f"{jn} #{jnum}"
    if jn:
        return jn
    if jnum:
        return f"#{jnum}"
    return fallback


def get_player_display_from_registration(player, registration) -> str:
    """
    Return a display string for a player using a known PlayerRegistration (no DB queries).
    """
    fallback = getattr(player, "name", "") or getattr(player, "id", "") or ""
    jersey_name = (
        getattr(registration, "jersey_name", None) if registration is not None else None
    )
    jersey_number = (
        getattr(registration, "jersey_number", None)
        if registration is not None
        else None
    )
    return format_jersey_display(
        jersey_name=jersey_name, jersey_number=jersey_number, fallback=fallback
    )


def get_player_display_name(
    player_id: str, tournament_url: str
) -> Tuple[Optional[str], Optional[str]]:
    """
    Get a player's canonical name and a tournament-specific display string.

    Display string preference:
    1) jersey_name + jersey_number (e.g. "Alice #7")
    2) jersey_name
    3) jersey_number (e.g. "#7")
    4) Player.name

    Returns:
        (player_name, player_display) or (None, None) if player not found.
    """
    if not player_id:
        return None, None

    # Local imports to avoid heavy import chains during app startup.
    from models import Player, PlayerRegistration

    player = Player.query.get(player_id)
    if not player:
        return None, None

    player_name = player.name
    player_display: Optional[str] = None

    if tournament_url:
        reg = PlayerRegistration.query.filter_by(
            event=tournament_url, player=player_id
        ).first()
        if reg:
            player_display = format_jersey_display(
                jersey_name=getattr(reg, "jersey_name", None),
                jersey_number=getattr(reg, "jersey_number", None),
                fallback=player.name,
            )

    if not player_display:
        player_display = player.name

    return player_name, player_display
