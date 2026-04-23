"""
User-type helper utilities.

These helpers are meant to replace brittle string checks like
`current_user.__class__.__name__ == 'Player'`.
"""

from __future__ import annotations


def is_player(user) -> bool:
    """Return whether *user* is a :class:`~app.models.user.Player` instance.

    Avoids brittle ``__class__.__name__`` string comparisons.

    Args:
        user: Any object, or ``None``.

    Returns:
        ``True`` if *user* is an instance of the ``Player`` model.
    """
    if user is None:
        return False
    from models import Player

    return isinstance(user, Player)


def is_team(user) -> bool:
    """Return whether *user* is a :class:`~app.models.user.Team` instance.

    Avoids brittle ``__class__.__name__`` string comparisons.

    Args:
        user: Any object, or ``None``.

    Returns:
        ``True`` if *user* is an instance of the ``Team`` model.
    """
    if user is None:
        return False
    from models import Team

    return isinstance(user, Team)
