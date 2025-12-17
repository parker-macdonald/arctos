"""
User-type helper utilities.

These helpers are meant to replace brittle string checks like
`current_user.__class__.__name__ == 'Player'`.
"""

from __future__ import annotations


def is_player(user) -> bool:
    """Return True if user is a Player model instance."""
    if user is None:
        return False
    from models import Player

    return isinstance(user, Player)


def is_team(user) -> bool:
    """Return True if user is a Team model instance."""
    if user is None:
        return False
    from models import Team

    return isinstance(user, Team)


