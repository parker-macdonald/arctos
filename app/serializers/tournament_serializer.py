"""Tournament-related serializer helpers.

- ``tournament_to_dict(t)`` - serialise a Tournament to the API dict.
- ``team_name_for_match(tournament, match, team_key)`` - resolve a team
  reference (id or slot ref) to a display name for the given match.

This module is currently a facade re-exporting the implementations from
``app.routes._api``. The tournaments-refactor PR replaces the
re-exports with the real implementations; consumers can import the
public names now and never have to change once the refactor lands.
"""

from __future__ import annotations

from app.routes._api import _team_name_for_match as team_name_for_match
from app.routes._api import _tournament_to_dict as tournament_to_dict

__all__ = ["team_name_for_match", "tournament_to_dict"]
