"""League lookup and serializer helpers.

- ``require_league(league_url)`` - league-lookup-with-403 helper. Returns
  a ``(league, error_code)`` tuple. Used as a permission gate by routes
  that need to verify the caller can see the league.
- ``league_to_dict(league)`` - serialise a League to the API dict shape.

This module is currently a facade re-exporting the implementations from
``app.routes._api``. The leagues-refactor PR replaces the re-exports
with the real implementations; consumers can import the public names
now and never have to change once the refactor lands.
"""

from __future__ import annotations

from app.routes._api import _league_to_dict as league_to_dict
from app.routes._api import _require_league as require_league

__all__ = ["league_to_dict", "require_league"]
