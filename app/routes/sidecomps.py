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
                            "registered_at": reg.registered_at.isoformat() if reg.registered_at else None,
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


@bp.route("/sidecomps/<int:comp_id>/register", methods=["POST"])
@login_required
def player_register(comp_id: int):
    """Player self-registration for a side competition."""
    if not is_player(current_user):
        return jsonify({"success": False, "error": "Only players can register"}), 403

    res = SideCompService.register_player(comp_id, player_id=current_user.id)
    match res:
        case Ok(reg):
            return jsonify(
                {
                    "success": True,
                    "comp": reg.comp,
                    "player_id": reg.player,
                    "registered_at": reg.registered_at.isoformat() if reg.registered_at else None,
                }
            )
        case Err(err):
            return _err_response(err)


@bp.route("/sidecomps/<int:comp_id>/deregister", methods=["POST"])
@login_required
def player_deregister(comp_id: int):
    """Player self-deregistration from a side competition."""
    if not is_player(current_user):
        return jsonify({"success": False, "error": "Only players can deregister"}), 403

    res = SideCompService.deregister_player(comp_id, player_id=current_user.id)
    match res:
        case Ok(_):
            return jsonify({"success": True})
        case Err(err):
            return _err_response(err)


@bp.route("/sidecomps/<int:comp_id>/checkin", methods=["POST"])
@login_required
def to_checkin(comp_id: int):
    """TO-only: check a player into a side competition."""
    if not request.is_json:
        return jsonify({"success": False, "error": "Content-Type must be application/json"}), 415
    data = request.get_json() or {}
    player_id = (data.get("player_id") or "").strip()
    if not player_id:
        return jsonify({"success": False, "error": "player_id is required"}), 400

    res = SideCompService.organizer_check_in(
        comp_id,
        actor_user_id=current_user.id,
        actor_user_type=current_user.__class__.__name__.lower(),
        player_id=player_id,
    )
    match res:
        case Ok(reg):
            from models import Player

            player = Player.query.get(reg.player)
            return jsonify(
                {
                    "success": True,
                    "player_id": reg.player,
                    "player_name": player.name if player else reg.player,
                    "registered_at": reg.registered_at.isoformat() if reg.registered_at else None,
                }
            )
        case Err(err):
            return _err_response(err)


@bp.route("/sidecomps/<int:comp_id>/uncheckin", methods=["POST"])
@login_required
def to_uncheckin(comp_id: int):
    """TO-only: remove a player from a side competition."""
    if not request.is_json:
        return jsonify({"success": False, "error": "Content-Type must be application/json"}), 415
    data = request.get_json() or {}
    player_id = (data.get("player_id") or "").strip()
    if not player_id:
        return jsonify({"success": False, "error": "player_id is required"}), 400

    res = SideCompService.organizer_remove(
        comp_id,
        actor_user_id=current_user.id,
        actor_user_type=current_user.__class__.__name__.lower(),
        player_id=player_id,
    )
    match res:
        case Ok(_):
            return jsonify({"success": True})
        case Err(err):
            return _err_response(err)


@bp.route("/sidecomps/<int:comp_id>/eligible-players", methods=["GET"])
@login_required
def eligible_players(comp_id: int):
    """TO-only: list players registered for the event but not yet in this side comp."""
    from app.domain.enums import RegistrationStatus
    from models import (
        Player,
        PlayerRegistration,
        SideComp,
        SideCompRegistration,
        TeamRegistration,
    )

    sc = SideComp.query.get(comp_id)
    if sc is None:
        return jsonify({"success": False, "error": "Side competition not found"}), 404

    auth_check = SideCompService._require_to(sc.event, current_user.id, current_user.__class__.__name__.lower())
    match auth_check:
        case Err(err):
            return _err_response(err)

    already_in = {r.player for r in SideCompRegistration.query.filter_by(comp=comp_id).all()}

    event_regs = PlayerRegistration.query.filter_by(
        event=sc.event,
        status=RegistrationStatus.CONFIRMED,
    ).all()

    out = []
    for er in event_regs:
        if er.player in already_in:
            continue
        player = Player.query.get(er.player)
        team_pseudonym = None
        if er.team:
            tr = TeamRegistration.query.filter_by(event=sc.event, team=er.team).first()
            team_pseudonym = tr.pseudonym if tr else None
        out.append(
            {
                "player_id": er.player,
                "player_name": player.name if player else er.player,
                "team_id": er.team,
                "team_pseudonym": team_pseudonym,
                "jersey_name": er.jersey_name,
            }
        )
    return jsonify(out)
