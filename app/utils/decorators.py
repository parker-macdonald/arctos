"""
Route decorators for common permissions.
"""

from __future__ import annotations

from functools import wraps

from flask import flash, redirect, request
from flask_login import current_user, login_required

from app.services.permission_service import PermissionService


def require_tournament_organizer(message: str = "Only tournament organizers can access this page"):
    """
    Require current user to be a TO for the given tournament.

    Assumes the wrapped route has `tournament_url` as the first positional arg or
    as a keyword arg.
    """

    def decorator(fn):
        @wraps(fn)
        @login_required
        def wrapper(*args, **kwargs):
            tournament_url = kwargs.get("tournament_url")
            if tournament_url is None and args:
                tournament_url = args[0]

            if not PermissionService.is_tournament_organizer(tournament_url, current_user):
                flash(message, "error")
                return redirect(request.referrer or f"/{tournament_url}")

            return fn(*args, **kwargs)

        return wrapper

    return decorator


