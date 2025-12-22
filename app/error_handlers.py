"""
Flask error handler registration.

We keep handlers conservative: if an ArctosError is raised, we surface a friendly
message. For API-ish requests we return JSON; otherwise we flash + redirect.
"""

from __future__ import annotations

from flask import Flask


def register_error_handlers(app: Flask) -> None:
    from flask import flash, redirect, request

    from app.exceptions import ArctosError
    from app.utils.responses import json_error

    @app.errorhandler(ArctosError)  # type: ignore[misc]
    def _handle_arctos_error(e: ArctosError):
        # Decide “API” vs “HTML” conservatively.
        # We treat the request as API when:
        # - it's under /api, or
        # - the client explicitly prefers JSON over HTML.
        accepts = request.accept_mimetypes
        prefers_json = (accepts.best == "application/json") and not accepts.accept_html
        is_api_path = request.path.startswith("/api")
        if request.is_json or is_api_path or prefers_json:
            # Keep prior behavior: many endpoints historically returned 200 even on errors.
            return json_error(e.message if e.public else "Request failed", status_code=200)

        flash(e.message if e.public else "Request failed", "error")
        return redirect(request.referrer or "/")


