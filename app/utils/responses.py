"""
Response helper utilities.

Helpers for building consistent JSON responses from Flask view functions.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from flask import Response, jsonify


def json_success(data: Optional[Dict[str, Any]] = None, status_code: int = 200) -> Tuple[Response, int]:
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


def json_error(message: str, status_code: int = 400, **extra: Any) -> Tuple[Response, int]:
    """Return a ``{"success": false, "error": "..."}`` JSON response.

    Defaults to HTTP 400 (Bad Request). Pass an explicit *status_code* when the
    route should signal a different error code (e.g. 403, 404).

    Args:
        message: Human-readable error description.
        status_code: HTTP status code to use (default 400).
        **extra: Additional key-value pairs merged into the response payload.

    Returns:
        A ``(Response, status_code)`` tuple suitable for returning from a
        Flask view function.
    """
    payload: Dict[str, Any] = {"success": False, "error": message}
    if extra:
        payload.update(extra)
    return jsonify(payload), status_code
