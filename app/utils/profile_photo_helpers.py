"""Helpers for the player/team profile-photo upload endpoints.

- ``profile_photo_upload_dir()`` - absolute disk directory where profile
  photos are stored.
- ``safe_profile_photo_filename(prefix, entity_id)`` - canonical
  per-entity filename, deterministic so a fresh upload always
  overwrites the previous photo.

This module is currently a facade re-exporting the implementations from
``app.routes._api``. The players/teams-refactor PR replaces the
re-exports with the real implementations; consumers can import the
public names now and never have to change once the refactor lands.
"""

from __future__ import annotations

from app.routes._api import _profile_photo_upload_dir as profile_photo_upload_dir
from app.routes._api import _safe_profile_photo_filename as safe_profile_photo_filename

__all__ = ["profile_photo_upload_dir", "safe_profile_photo_filename"]
