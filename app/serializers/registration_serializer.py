"""Serializers for registration responses.

Two pure-function builders used by registration routes:

- ``player_reg_waiver_api(reg, cfg)`` - builds the waiver-status sub-dict
  embedded in player-registration API payloads.
- ``serialize_manage(scope, search_query, search_type, cfg)`` - builds
  the full registration-management response payload used by league and
  tournament TO views.

This module is currently a facade re-exporting the implementations from
``app.routes._api``. The registration-refactor PR replaces the
re-exports with the real implementations; consumers can import the
public names now and never have to change once the refactor lands.
"""

from __future__ import annotations

from app.routes._api import _player_reg_waiver_api as player_reg_waiver_api
from app.routes._api import _serialize_manage as serialize_manage

__all__ = ["player_reg_waiver_api", "serialize_manage"]
