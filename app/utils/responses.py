"""
Response helper utilities.

Keep the existing API behavior stable: by default, Arctos has historically
returned JSON error payloads with HTTP 200 for many endpoints. These helpers
therefore default to status_code=200 unless a caller overrides it.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from flask import Response, jsonify


def json_success(data: Optional[Dict[str, Any]] = None, status_code: int = 200) -> Tuple[Response, int]:
    payload: Dict[str, Any] = {"success": True}
    if data:
        payload.update(data)
    return jsonify(payload), status_code


def json_error(message: str, status_code: int = 200, **extra: Any) -> Tuple[Response, int]:
    payload: Dict[str, Any] = {"success": False, "error": message}
    if extra:
        payload.update(extra)
    return jsonify(payload), status_code


