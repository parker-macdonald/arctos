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


@bp.route("/<tournament_url>/sidecomps", methods=["GET"])
def list_for_event(tournament_url: str):
    """Public: list side competitions for a tournament.

    Returns a JSON array of summaries:
    ``[{id, name, type, registrant_count, created_at}, ...]``.
    """
    from models import SideCompRegistration

    rows = SideCompService.list_for_event(tournament_url)
    out = []
    for sc in rows:
        count = SideCompRegistration.query.filter_by(comp=sc.id).count()
        out.append(
            {
                "id": sc.id,
                "name": sc.name,
                "type": str(sc.type),
                "registrant_count": count,
                "created_at": sc.created_at.isoformat() if sc.created_at else None,
            }
        )
    return jsonify(out)


@bp.route("/sidecomps/<int:comp_id>", methods=["GET"])
def detail(comp_id: int):
    """Public: side competition detail with registrants."""
    res = SideCompService.get_with_registrants(comp_id)
    match res:
        case Ok((sc, registrants)):
            return jsonify(
                {
                    "id": sc.id,
                    "event": sc.event,
                    "name": sc.name,
                    "type": str(sc.type),
                    "created_at": sc.created_at.isoformat() if sc.created_at else None,
                    "registrants": [
                        {
                            "player_id": reg.player,
                            "player_name": (player.name if player else reg.player),
                            "registered_at": reg.registered_at.isoformat()
                            if reg.registered_at
                            else None,
                            "registered_by_to": bool(reg.registered_by_to),
                        }
                        for reg, player in registrants
                    ],
                }
            )
        case Err(err):
            return _err_response(err)


@bp.route("/<tournament_url>/sidecomps", methods=["POST"])
@login_required
def create(tournament_url: str):
    """TO-only: create a side competition."""
    if not request.is_json:
        return jsonify({"success": False, "error": "Content-Type must be application/json"}), 415
    data = request.get_json() or {}

    res = SideCompService.create(
        tournament_url,
        actor_user_id=current_user.id,
        actor_user_type=current_user.__class__.__name__.lower(),
        name=data.get("name", ""),
        type=data.get("type", ""),
    )
    match res:
        case Ok(sc):
            return jsonify(
                {
                    "id": sc.id,
                    "event": sc.event,
                    "name": sc.name,
                    "type": str(sc.type),
                    "created_at": sc.created_at.isoformat() if sc.created_at else None,
                }
            )
        case Err(err):
            return _err_response(err)


@bp.route("/sidecomps/<int:comp_id>", methods=["PATCH"])
@login_required
def update(comp_id: int):
    """TO-only: rename or change type of a side competition."""
    if not request.is_json:
        return jsonify({"success": False, "error": "Content-Type must be application/json"}), 415
    data = request.get_json() or {}

    res = SideCompService.update(
        comp_id,
        actor_user_id=current_user.id,
        actor_user_type=current_user.__class__.__name__.lower(),
        name=data.get("name"),
        type=data.get("type"),
    )
    match res:
        case Ok(sc):
            return jsonify(
                {
                    "id": sc.id,
                    "event": sc.event,
                    "name": sc.name,
                    "type": str(sc.type),
                }
            )
        case Err(err):
            return _err_response(err)


@bp.route("/sidecomps/<int:comp_id>", methods=["DELETE"])
@login_required
def delete(comp_id: int):
    """TO-only: hard-delete a side competition and its registrations/results."""
    res = SideCompService.delete(
        comp_id,
        actor_user_id=current_user.id,
        actor_user_type=current_user.__class__.__name__.lower(),
    )
    match res:
        case Ok(_):
            return jsonify({"success": True})
        case Err(err):
            return _err_response(err)
