"""Helpers for the player/team profile-photo upload endpoints."""

from __future__ import annotations

import os

from flask import current_app


def profile_photo_upload_dir() -> str:
    """Return the absolute directory where profile photos are stored on disk."""
    return os.path.join(current_app.root_path, "..", "static", "uploads", "profiles")


def safe_profile_photo_filename(prefix: str, entity_id: str) -> str:
    """Sanitize *entity_id* for safe use in a filename and return the canonical
    profile-photo filename for the given prefix (``"player"`` or ``"team"``).

    Replaces every character that is not alphanumeric or underscore with an
    underscore, then appends ``.jpg``. The resulting filename is predictable
    and deterministic per entity, so a fresh upload always overwrites the
    previous photo.
    """
    safe = "".join(c if c.isalnum() or c == "_" else "_" for c in entity_id)
    return f"{prefix}_{safe}.jpg"
