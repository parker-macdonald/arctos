"""
Flask error handler registration.

We keep handlers conservative: if an ArctosError is raised, we surface a friendly
message. For API-ish requests we return JSON; otherwise we flash + redirect.
"""

from __future__ import annotations

from flask import Flask


def register_error_handlers(app: Flask) -> None:
    """Register domain-level error handlers on the Flask application.

    Attaches a single handler for :class:`~app.exceptions.ArctosError`
    (and all subclasses) that decides whether to respond with JSON or an
    HTML flash-and-redirect based on the request context:

    * Requests to ``/_api/…`` paths always receive a JSON error body.
    * Requests that ``Accept: application/json`` (and not HTML) receive JSON.
    * All other requests receive a flashed message and a redirect to the
      referring page.

    Args:
        app: The Flask application instance to register handlers on.
    """
    from flask import flash, redirect, request

    from app.exceptions import ArctosError
    from app.utils.decorators import _wants_json
    from app.utils.responses import json_error

    @app.errorhandler(ArctosError)  # type: ignore[misc]
    def _handle_arctos_error(e: ArctosError):
        if _wants_json(request):
            # Surface the domain status_code so SPA clients can distinguish 4xx/5xx by HTTP status.
            return json_error(e.message if e.public else "Request failed", status_code=e.status_code)

        flash(e.message if e.public else "Request failed", "error")
        return redirect(request.referrer or "/")
