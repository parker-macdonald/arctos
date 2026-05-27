"""
Route decorators for common permissions.
"""

from __future__ import annotations

from functools import wraps

from flask import flash, g, redirect, request
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


def _require_organizer(
    *,
    param_name: str,
    check_fn,
    redirect_path_fn,
    message: str,
):
    """Internal builder for organiser-role decorators.

    Args:
        param_name: Name of the URL slug kwarg (``"tournament_url"`` or
            ``"league_url"``) the decorated view exposes.
        check_fn: Callable ``(slug, user) -> bool`` from
            :class:`~app.services.permission_service.PermissionService`.
        redirect_path_fn: Callable ``(slug) -> str`` building the HTML
            redirect fallback when no referrer is set.
        message: Error message shown to unauthorised users.

    Returns:
        A decorator that wraps a Flask route function with
        :func:`~flask_login.login_required` and the organiser check.
    """
    from app.utils.responses import json_error

    def decorator(fn):
        @wraps(fn)
        @login_required
        def wrapper(*args, **kwargs):
            slug = kwargs.get(param_name)
            if slug is None and args:
                slug = args[0]

            if not check_fn(slug, current_user):
                if wants_json(request):
                    return json_error(message, status_code=403)
                flash(message, "error")
                return redirect(request.referrer or redirect_path_fn(slug))

            return fn(*args, **kwargs)

        return wrapper

    return decorator


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
    return _require_organizer(
        param_name="tournament_url",
        check_fn=PermissionService.is_tournament_organizer,
        redirect_path_fn=lambda slug: f"/{slug}",
        message=message,
    )


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
    return _require_organizer(
        param_name="league_url",
        check_fn=PermissionService.is_league_organizer,
        redirect_path_fn=lambda slug: f"/leagues/{slug}",
        message=message,
    )


def require_json_body():
    """Decorator factory that guards a route's body to be JSON.

    On a non-JSON request the decorator returns
    ``json_error("Content-Type must be application/json", status_code=415)``.
    On success the parsed body (or ``{}`` if empty) is stashed on
    :data:`flask.g.json_body` for the view to consume.

    Returns:
        A decorator that wraps a Flask route function.
    """
    from app.utils.responses import json_error

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not request.is_json:
                return json_error("Content-Type must be application/json", status_code=415)
            parsed = request.get_json(silent=True)
            # Distinguish empty body (parsed is None AND no data) from malformed JSON
            # (parsed is None BUT data is present).
            if parsed is None and request.data:
                return json_error("Invalid JSON body", status_code=400)
            g.json_body = parsed if parsed is not None else {}
            return fn(*args, **kwargs)

        return wrapper

    return decorator
