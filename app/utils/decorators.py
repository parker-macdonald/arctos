"""
Route decorators for common permissions.
"""

from __future__ import annotations

from functools import wraps

from flask import flash, redirect, request
from flask_login import current_user, login_required

from app.services.permission_service import PermissionService


def wants_json(request) -> bool:
    """Return whether *request* should receive a JSON response.

    Mirrors the sniffer used in :mod:`app.error_handlers`. A request is
    treated as JSON-preferring when any of the following hold:

    - the body is JSON (``request.is_json``);
    - the path is under ``/_api`` (the SPA's API namespace); or
    - the ``Accept`` header explicitly prefers JSON over HTML.
    """
    accepts = request.accept_mimetypes
    prefers_json = accepts.best == "application/json" and not accepts.accept_html
    is_api_path = request.path.startswith("/_api")
    return request.is_json or is_api_path or prefers_json


def require_tournament_organizer(
    message: str = "Only tournament organizers can access this page",
):
    """Decorator factory that guards a route to Tournament Organisers only.

    Wraps the decorated view with :func:`~flask_login.login_required`.  On
    failure the response shape matches the request:

    - JSON requests (``Accept: application/json``, ``/_api`` paths,
      JSON bodies) receive ``json_error(message, status_code=403)``.
    - HTML requests are flashed *message* and redirected to the referrer
      (or ``/<tournament_url>``).

    The decorated route MUST expose ``tournament_url`` as its first
    positional argument or as a keyword argument.

    Args:
        message: Error message shown to unauthorised users.

    Returns:
        A decorator that wraps a Flask route function.

    Example::

        @bp.route("/<tournament_url>/settings", methods=["POST"])
        @require_tournament_organizer()
        def update_settings(tournament_url: str):
            ...
    """
    from app.utils.responses import json_error

    def decorator(fn):
        @wraps(fn)
        @login_required
        def wrapper(*args, **kwargs):
            tournament_url = kwargs.get("tournament_url")
            if tournament_url is None and args:
                tournament_url = args[0]

            if not PermissionService.is_tournament_organizer(tournament_url, current_user):
                if wants_json(request):
                    return json_error(message, status_code=403)
                flash(message, "error")
                return redirect(request.referrer or f"/{tournament_url}")

            return fn(*args, **kwargs)

        return wrapper

    return decorator


def require_league_organizer(
    message: str = "Only league organizers can access this page",
):
    """Decorator factory that guards a route to League Organisers only.

    Mirrors :func:`require_tournament_organizer` but checks
    :meth:`~app.services.permission_service.PermissionService.is_league_organizer`.
    The decorated route MUST expose ``league_url`` as its first positional
    argument or as a keyword argument.

    Args:
        message: Error message shown to unauthorised users.

    Returns:
        A decorator that wraps a Flask route function.
    """
    from app.utils.responses import json_error

    def decorator(fn):
        @wraps(fn)
        @login_required
        def wrapper(*args, **kwargs):
            league_url = kwargs.get("league_url")
            if league_url is None and args:
                league_url = args[0]

            if not PermissionService.is_league_organizer(league_url, current_user):
                if wants_json(request):
                    return json_error(message, status_code=403)
                flash(message, "error")
                return redirect(request.referrer or f"/leagues/{league_url}")

            return fn(*args, **kwargs)

        return wrapper

    return decorator
