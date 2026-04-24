"""
Response helper utilities.

Keep the existing API behavior stable: by default, Arctos has historically
returned JSON error payloads with HTTP 200 for many endpoints. These helpers
therefore default to status_code=200 unless a caller overrides it.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from flask import Response, jsonify


def json_success(
    data: Optional[Dict[str, Any]] = None, status_code: int = 200
) -> Tuple[Response, int]:
    """Return a ``{"success": true, ...}`` JSON response.

    Args:
        data: Optional dict of additional fields to merge into the payload.
        status_code: HTTP status code to use (default 200).

    Returns:
        A ``(Response, status_code)`` tuple suitable for returning from a
        Flask view function.
    """
    payload: Dict[str, Any] = {"success": True}
    if data:
        payload.update(data)
    return jsonify(payload), status_code


def json_error(
    message: str, status_code: int = 200, **extra: Any
) -> Tuple[Response, int]:
    """Return a ``{"success": false, "error": "..."}`` JSON response.

    Defaults to HTTP 200 to preserve historical API compatibility.  Pass an
    explicit *status_code* when the client needs a real error code.

    Args:
        message: Human-readable error description.
        status_code: HTTP status code to use (default 200).
        **extra: Additional key-value pairs merged into the response payload.

    Returns:
        A ``(Response, status_code)`` tuple suitable for returning from a
        Flask view function.
    """
    payload: Dict[str, Any] = {"success": False, "error": message}
    if extra:
        payload.update(extra)
    return jsonify(payload), status_code
