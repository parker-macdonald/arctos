"""Side competition routes."""

from flask import Blueprint, g, jsonify
from flask_login import login_required, current_user  # type: ignore[import-untyped]

from app.services._common import current_user_type
from app.services.permission_service import PermissionService
from app.services.sidecomp_service import SideCompService
from app.utils.decorators import require_json_body
from app.utils.result_helpers import json_from_result
from app.utils.user_helpers import is_player

bp = Blueprint("sidecomps", __name__, url_prefix="/_api")


@bp.route("/<tournament_url>/sidecomps", methods=["GET"])
def list_for_event(tournament_url: str):
    """Public: list side competitions for a tournament.

    Returns a JSON array of summaries:
    ``[{id, name, type, registrant_count, created_at}, ...]``.
    """
    from sqlalchemy import func
    from models import SideComp, SideCompRegistration, db

    rows = (
        db.session.query(SideComp, func.count(SideCompRegistration.id))
        .outerjoin(SideCompRegistration, SideCompRegistration.comp == SideComp.id)
        .filter(SideComp.event == tournament_url)
        .group_by(SideComp.id)
        .order_by(SideComp.created_at.asc())
        .all()
    )
    out = [
        {
            "id": sc.id,
            "name": sc.name,
            "type": str(sc.type),
            "registrant_count": count,
            "registration_open": bool(sc.registration_open),
            "created_at": sc.created_at.isoformat() if sc.created_at else None,
        }
        for sc, count in rows
    ]
    return jsonify(out)


def _detail_payload(sc, registrants):
    entry_numbers = SideCompService.entry_numbers_for_tournament(sc.event)
    viewer_is_to = False
    viewer_can_register = False
    viewer_is_registered_in_comp = False
    if current_user.is_authenticated:
        viewer_is_to = PermissionService.is_tournament_organizer(sc.event, current_user)
        if is_player(current_user):
            viewer_is_registered_in_comp = any(reg.player == current_user.id for reg, _ in registrants)
            if not viewer_is_registered_in_comp and sc.registration_open:
                event_reg = SideCompService._confirmed_player_registration_for_tournament(sc.event, current_user.id)
                viewer_can_register = event_reg is not None

    return {
        "id": sc.id,
        "event": sc.event,
        "name": sc.name,
        "type": str(sc.type),
        "description": sc.description,
        "registration_open": bool(sc.registration_open),
        "created_at": sc.created_at.isoformat() if sc.created_at else None,
        "registrants": [
            {
                "player_id": reg.player,
                "player_name": (player.name if player else reg.player),
                "entry_number": entry_numbers.get(reg.player),
                "registered_at": reg.registered_at.isoformat() if reg.registered_at else None,
                "registered_by_to": bool(reg.registered_by_to),
            }
            for reg, player in registrants
        ],
        "viewer_is_to": viewer_is_to,
        "viewer_can_register": viewer_can_register,
        "viewer_is_registered_in_comp": viewer_is_registered_in_comp,
    }


@bp.route("/sidecomps/<int:comp_id>", methods=["GET"])
def detail(comp_id: int):
    """Public: side competition detail with registrants and viewer-context flags."""
    res = SideCompService.get_with_registrants(comp_id)
    return json_from_result(res, ok_to_payload=lambda v: _detail_payload(v[0], v[1]))


@bp.route("/<tournament_url>/sidecomps", methods=["POST"])
@login_required
@require_json_body()
def create(tournament_url: str):
    """TO-only: create a side competition."""
    data = g.json_body

    res = SideCompService.create(
        tournament_url,
        actor_user_id=current_user.id,
        actor_user_type=current_user_type(),
        name=data.get("name", ""),
        type=data.get("type", ""),
        description=data.get("description"),
    )
    return json_from_result(
        res,
        ok_to_payload=lambda sc: {
            "id": sc.id,
            "event": sc.event,
            "name": sc.name,
            "type": str(sc.type),
            "description": sc.description,
            "registration_open": bool(sc.registration_open),
            "created_at": sc.created_at.isoformat() if sc.created_at else None,
        },
    )


@bp.route("/sidecomps/<int:comp_id>", methods=["PATCH"])
@login_required
@require_json_body()
def update(comp_id: int):
    """TO-only: rename or change type of a side competition."""
    data = g.json_body

    res = SideCompService.update(
        comp_id,
        actor_user_id=current_user.id,
        actor_user_type=current_user_type(),
        name=data.get("name"),
        type=data.get("type"),
        description=data.get("description"),
        registration_open=data.get("registration_open"),
    )
    return json_from_result(
        res,
        ok_to_payload=lambda sc: {
            "id": sc.id,
            "event": sc.event,
            "name": sc.name,
            "type": str(sc.type),
            "description": sc.description,
            "registration_open": bool(sc.registration_open),
        },
    )


@bp.route("/sidecomps/<int:comp_id>", methods=["DELETE"])
@login_required
def delete(comp_id: int):
    """TO-only: hard-delete a side competition and its registrations/results."""
    res = SideCompService.delete(
        comp_id,
        actor_user_id=current_user.id,
        actor_user_type=current_user_type(),
    )
    return json_from_result(res, ok_to_payload=lambda _: {})


@bp.route("/sidecomps/<int:comp_id>/register", methods=["POST"])
@login_required
def player_register(comp_id: int):
    """Player self-registration for a side competition."""
    if not is_player(current_user):
        return jsonify({"success": False, "error": "Only players can register"}), 403

    res = SideCompService.register_player(comp_id, player_id=current_user.id)
    return json_from_result(
        res,
        ok_to_payload=lambda reg: {
            "comp": reg.comp,
            "player_id": reg.player,
            "registered_at": reg.registered_at.isoformat() if reg.registered_at else None,
        },
    )


@bp.route("/sidecomps/<int:comp_id>/deregister", methods=["POST"])
@login_required
def player_deregister(comp_id: int):
    """Player self-deregistration from a side competition."""
    if not is_player(current_user):
        return jsonify({"success": False, "error": "Only players can deregister"}), 403

    res = SideCompService.deregister_player(comp_id, player_id=current_user.id)
    return json_from_result(res, ok_to_payload=lambda _: {})


@bp.route("/sidecomps/<int:comp_id>/register-player-as-to", methods=["POST"])
@login_required
@require_json_body()
def register_player_as_to(comp_id: int):
    """TO-only: register a player into a side competition on their behalf."""
    data = g.json_body
    player_id = (data.get("player_id") or "").strip()
    if not player_id:
        return jsonify({"success": False, "error": "player_id is required"}), 400

    res = SideCompService.register_player_as_to(
        comp_id,
        actor_user_id=current_user.id,
        actor_user_type=current_user_type(),
        player_id=player_id,
    )

    def _checkin_payload(reg):
        from models import Player, SideComp

        player = Player.query.get(reg.player)
        sc = SideComp.query.get(reg.comp)
        entry_number = SideCompService.entry_number_for(sc.event, reg.player) if sc else None
        return {
            "player_id": reg.player,
            "player_name": player.name if player else reg.player,
            "entry_number": entry_number,
            "registered_at": reg.registered_at.isoformat() if reg.registered_at else None,
        }

    return json_from_result(res, ok_to_payload=_checkin_payload)


@bp.route("/sidecomps/<int:comp_id>/deregister-player-as-to", methods=["POST"])
@login_required
@require_json_body()
def deregister_player_as_to(comp_id: int):
    """TO-only: deregister a player from a side competition on their behalf."""
    data = g.json_body
    player_id = (data.get("player_id") or "").strip()
    if not player_id:
        return jsonify({"success": False, "error": "player_id is required"}), 400

    res = SideCompService.deregister_player_as_to(
        comp_id,
        actor_user_id=current_user.id,
        actor_user_type=current_user_type(),
        player_id=player_id,
    )
    return json_from_result(res, ok_to_payload=lambda _: {})


@bp.route("/sidecomps/<int:comp_id>/eligible-players", methods=["GET"])
@login_required
def eligible_players(comp_id: int):
    """TO-only: list event-registered players with side competition status."""
    from app.domain.enums import RegistrationStatus
    from app.services.registration_resolver import (
        player_registrations_for_tournament,
        team_registrations_for_tournament,
    )
    from models import (
        Player,
        SideComp,
        SideCompRegistration,
        Tournament,
    )

    sc = SideComp.query.get(comp_id)
    if sc is None:
        return jsonify({"success": False, "error": "Side competition not found"}), 404

    auth_check = SideCompService._require_to(sc.event, current_user.id, current_user_type())
    if auth_check.is_err():
        return json_from_result(auth_check)

    tournament = Tournament.query.get(sc.event)

    sidecomp_regs = {r.player: r for r in SideCompRegistration.query.filter_by(comp=comp_id).all()}
    entry_numbers = SideCompService.entry_numbers_for_tournament(sc.event)

    event_regs = player_registrations_for_tournament(tournament, statuses=[RegistrationStatus.CONFIRMED])

    player_ids = [er.player for er in event_regs]
    team_ids = {er.team for er in event_regs if er.team}

    players_by_id = {p.id: p for p in Player.query.filter(Player.id.in_(player_ids)).all()} if player_ids else {}
    team_pseudonyms = {}
    team_shortnames = {}
    if team_ids:
        for tr in team_registrations_for_tournament(tournament):
            if tr.team in team_ids:
                team_pseudonyms[tr.team] = tr.pseudonym
                team_shortnames[tr.team] = tr.shortname

    out = [
        {
            "player_id": er.player,
            "player_name": players_by_id[er.player].name if er.player in players_by_id else er.player,
            "team_id": er.team,
            "team_pseudonym": team_pseudonyms.get(er.team) if er.team else None,
            "team_shortname": team_shortnames.get(er.team) if er.team else None,
            "jersey_name": er.jersey_name,
            "sidecomp_registered": er.player in sidecomp_regs,
            "entry_number": entry_numbers.get(er.player) if er.player in sidecomp_regs else None,
        }
        for er in event_regs
    ]
    return jsonify(out)
