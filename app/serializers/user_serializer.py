"""Serializer for the current authenticated user.

The ``user_json`` helper returns the minimal JSON-safe dictionary used
by ``/me``, ``/login``, ``/register``, and the Google OAuth completion
endpoints. The dict shape is part of the API contract:

    {
        "id":           str,
        "name":         str,
        "type":         "player" | "team",
        "has_password": bool,
    }

When the current user is not authenticated, returns ``None``.

This module is currently a facade re-exporting the implementation from
``app.routes._api``. The auth-refactor PR replaces the re-export with
the real implementation; consumers can import the public name now and
never have to change once the refactor lands.
"""

from __future__ import annotations

from app.routes._api import _user_json as user_json

__all__ = ["user_json"]
