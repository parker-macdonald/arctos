"""
Route decorators for common permissions.
"""

from __future__ import annotations

from functools import wraps

from flask import flash, redirect, request
from flask_login import current_user, login_required

from app.services.permission_service import PermissionService


def require_tournament_organizer(
    message: str = "Only tournament organizers can access this page",
):
    """Decorator factory that guards a route to Tournament Organisers only.

    Wraps the decorated view function with :func:`~flask_login.login_required`
    and checks :meth:`~app.services.permission_service.PermissionService.is_tournament_organizer`.
    On failure it flashes *message* and redirects to the referring page (or
    ``/<tournament_url>``).

    The decorated route **must** expose ``tournament_url`` either as its
    first positional argument or as a keyword argument.

    Args:
        message: Flash message shown to unauthorised users.

    Returns:
        A decorator that wraps a Flask route function.

    Example::

        @bp.route("/<tournament_url>/settings", methods=["POST"])
        @require_tournament_organizer()
        def update_settings(tournament_url: str):
            ...
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
