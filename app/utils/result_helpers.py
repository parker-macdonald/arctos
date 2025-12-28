from __future__ import annotations

from typing import Any, Callable, TypeVar

from app.error_values import Err, Ok, Result
from app.exceptions import ArctosError
from app.utils.responses import json_error, json_success


def public_error_message(err: Any) -> str:
    """
    Convert an error value into a safe end-user message.
    """
    if isinstance(err, ArctosError):
        return err.message if err.public else "Request failed"
    return str(err) or "Request failed"


T = TypeVar("T")
E = TypeVar("E")


def json_from_result(
    res: Result[T, E],
    *,
    ok_to_payload: Callable[[T], dict] = lambda v: (
        v if isinstance(v, dict) else {"value": v}
    ),
    ok_status_code: int = 200,
    err_status_code: int | None = None,
):
    """
    Convert a Result into the standard {success: bool, ...} JSON response.

    - Ok -> json_success(payload)
    - Err -> json_error(message, status_code)

    If err_status_code is None and the error is an ArctosError, its status_code is used.
    Otherwise defaults to 200 (historical API compatibility).
    """
    match res:
        case Ok(val):
            return json_success(ok_to_payload(val), status_code=ok_status_code)
        case Err(err):
            status = 200
            if err_status_code is not None:
                status = err_status_code
            elif isinstance(err, ArctosError):
                status = err.status_code
            return json_error(public_error_message(err), status_code=status)
