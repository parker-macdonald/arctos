"""Side competition routes."""

from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user  # type: ignore[import-untyped]

from app.error_values import Err, Ok
from app.exceptions import ArctosError
from app.services.sidecomp_service import SideCompService
from app.utils.result_helpers import public_error_message
from app.utils.user_helpers import is_player

bp = Blueprint("sidecomps", __name__, url_prefix="/_api")


def _err_response(err):
    status = err.status_code if isinstance(err, ArctosError) else 400
    return jsonify({"success": False, "error": public_error_message(err)}), status
