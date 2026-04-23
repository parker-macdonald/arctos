"""
Tournament registration management routes.
"""

from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user  # type: ignore[import-untyped]
from datetime import datetime, timezone
from models import (
    Tournament,
    TeamRegistration,
    PlayerRegistration,
    Team,
    Player,
    TO,
    db,
)
from app.domain.enums import RegistrationStatus
from app.utils.decorators import require_tournament_organizer
from app.services.registration_service import RegistrationService
from app.utils.user_helpers import is_player, is_team
from app.error_values import Ok, Err
from app.utils.result_helpers import public_error_message

bp = Blueprint("registration", __name__, url_prefix="/_api")


@bp.route("/<tournament_url>/register-team", methods=["POST"])
@login_required
def register_team_for_tournament(tournament_url):
    """Register a team for a tournament."""
    if not is_team(current_user):
        return (
            jsonify(
                {"success": False, "error": "Only teams can register for tournaments"}
            ),
            403,
        )

    res = RegistrationService.register_team(
        tournament_url, current_user.id, request.form.get("pseudonym", "")
    )
    match res:
        case Ok(_):
            return (
                jsonify({"success": True, "message": "Team registration successful!"}),
                200,
            )
        case Err(err):
            return jsonify({"success": False, "error": public_error_message(err)}), 400


@bp.route("/<tournament_url>/register-player", methods=["POST"])
@login_required
def register_player_for_tournament(tournament_url):
    """Register a player for a tournament."""
    if not is_player(current_user):
        return (
            jsonify(
                {"success": False, "error": "Only players can register for tournaments"}
            ),
            403,
        )

    team_id = request.form.get("team", "") or None
    res = RegistrationService.register_player(
        tournament_url,
        current_user.id,
        team_id,
        jersey_number=request.form.get("jersey_number", ""),
        jersey_name=request.form.get("jersey_name", ""),
        waiver_legal_name_signature=request.form.get("waiver_legal_name_signature", ""),
    )
    match res:
        case Ok(_):
            if team_id:
                msg = "Registration submitted! The team will need to approve your request."
            else:
                msg = "Player registration successful! You are now registered for the tournament."
            return jsonify({"success": True, "message": msg}), 200
        case Err(err):
            return jsonify({"success": False, "error": public_error_message(err)}), 400


@bp.route("/<tournament_url>/deregister-team", methods=["POST"])
@login_required
def deregister_team_from_tournament(tournament_url):
    """Deregister a team from a tournament."""
    if not is_team(current_user):
        return (
            jsonify(
                {
                    "success": False,
                    "error": "Only teams can deregister from tournaments",
                }
            ),
            403,
        )

    res = RegistrationService.deregister_team(tournament_url, current_user.id)
    match res:
        case Ok(_):
            return (
                jsonify(
                    {
                        "success": True,
                        "message": "Team successfully deregistered from tournament",
                    }
                ),
                200,
            )
        case Err(err):
            return jsonify({"success": False, "error": public_error_message(err)}), 400


@bp.route("/<tournament_url>/deregister-player", methods=["POST"])
@login_required
def deregister_player_from_tournament(tournament_url):
    """Deregister a player from a tournament."""
    if not is_player(current_user):
        return (
            jsonify(
                {
                    "success": False,
                    "error": "Only players can deregister from tournaments",
                }
            ),
            403,
        )

    res = RegistrationService.deregister_player(tournament_url, current_user.id)
    match res:
        case Ok(_):
            return (
                jsonify(
                    {
                        "success": True,
                        "message": "Player successfully deregistered from tournament",
                    }
                ),
                200,
            )
        case Err(err):
            return jsonify({"success": False, "error": public_error_message(err)}), 400


@bp.route("/<tournament_url>/mark-team-paid", methods=["POST"])
@login_required
def mark_team_paid(tournament_url):
    """Mark team payment status."""
    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()
    is_to = TO.query.filter_by(
        user_id=current_user.id,
        user_type=current_user.__class__.__name__.lower(),
        event=tournament_url,
    ).first()
    if not is_to:
        return (
            jsonify(
                {
                    "success": False,
                    "error": "Only tournament organizers can perform this action",
                }
            ),
            403,
        )

    reg_id = request.form.get("registration_id")
    paid = request.form.get("paid") == "on"
    amount_paid = float(request.form.get("amount_paid") or 0)
    payment_method = request.form.get("payment_method", "")
    payment_reference = request.form.get("payment_reference", "")
    payment_notes = request.form.get("payment_notes", "")

    reg = TeamRegistration.query.filter_by(
        id=reg_id, event=tournament_url
    ).first_or_404()
    reg.paid = paid
    reg.amount_paid = amount_paid
    reg.payment_method = payment_method
    reg.payment_reference = payment_reference
    reg.payment_notes = payment_notes
    reg.paid_at = datetime.now(timezone.utc).replace(tzinfo=None) if paid else None
    db.session.commit()
    return jsonify({"success": True, "message": "Team payment updated"}), 200


@bp.route("/<tournament_url>/mark-player-paid", methods=["POST"])
@login_required
def mark_player_paid(tournament_url):
    """Mark player payment status."""
    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()
    is_to = TO.query.filter_by(
        user_id=current_user.id,
        user_type=current_user.__class__.__name__.lower(),
        event=tournament_url,
    ).first()
    if not is_to:
        return (
            jsonify(
                {
                    "success": False,
                    "error": "Only tournament organizers can perform this action",
                }
            ),
            403,
        )

    reg_id = request.form.get("registration_id")
    paid = request.form.get("paid") == "on"
    amount_paid = float(request.form.get("amount_paid") or 0)
    payment_method = request.form.get("payment_method", "")
    payment_reference = request.form.get("payment_reference", "")
    payment_notes = request.form.get("payment_notes", "")

    reg = PlayerRegistration.query.filter_by(
        id=reg_id, event=tournament_url
    ).first_or_404()
    reg.paid = paid
    reg.amount_paid = amount_paid
    reg.payment_method = payment_method
    reg.payment_reference = payment_reference
    reg.payment_notes = payment_notes
    reg.paid_at = datetime.now(timezone.utc).replace(tzinfo=None) if paid else None
    db.session.commit()
    return jsonify({"success": True, "message": "Player payment updated"}), 200


@bp.route("/<tournament_url>/deregister-any-team", methods=["POST"])
@login_required
def deregister_any_team(tournament_url):
    """Deregister any team (TO only)."""
    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()

    is_to = TO.query.filter_by(
        user_id=current_user.id,
        user_type=current_user.__class__.__name__.lower(),
        event=tournament_url,
    ).first()

    if not is_to:
        return (
            jsonify(
                {
                    "success": False,
                    "error": "Only tournament organizers can perform this action",
                }
            ),
            403,
        )

    team_id = request.form.get("team_id")
    if not team_id:
        return jsonify({"success": False, "error": "Team ID is required"}), 400

    team_registration = TeamRegistration.query.filter_by(
        event=tournament_url, team=team_id, status=RegistrationStatus.CONFIRMED
    ).first()

    if team_registration:
        team_registration.status = RegistrationStatus.CANCELLED

        PlayerRegistration.query.filter_by(event=tournament_url, team=team_id).update(
            {"status": RegistrationStatus.CANCELLED}
        )

        db.session.commit()
        return (
            jsonify({"success": True, "message": "Team successfully deregistered"}),
            200,
        )
    else:
        return (
            jsonify(
                {"success": False, "error": "Team not found or already deregistered"}
            ),
            404,
        )


@bp.route("/<tournament_url>/deregister-any-player", methods=["POST"])
@login_required
def deregister_any_player(tournament_url):
    """Deregister any player (TO only)."""
    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()

    is_to = TO.query.filter_by(
        user_id=current_user.id,
        user_type=current_user.__class__.__name__.lower(),
        event=tournament_url,
    ).first()

    if not is_to:
        return (
            jsonify(
                {
                    "success": False,
                    "error": "Only tournament organizers can perform this action",
                }
            ),
            403,
        )

    player_id = request.form.get("player_id")
    if not player_id:
        return jsonify({"success": False, "error": "Player ID is required"}), 400

    player_registration = (
        PlayerRegistration.query.filter_by(event=tournament_url, player=player_id)
        .filter(
            PlayerRegistration.status.in_(
                [RegistrationStatus.PENDING_TEAM_APPROVAL, RegistrationStatus.CONFIRMED]
            )
        )
        .first()
    )

    if player_registration:
        player_registration.status = RegistrationStatus.CANCELLED

        db.session.commit()
        return (
            jsonify({"success": True, "message": "Player successfully deregistered"}),
            200,
        )
    else:
        return (
            jsonify(
                {"success": False, "error": "Player not found or already deregistered"}
            ),
            404,
        )


@bp.route("/<tournament_url>/invitation/<int:invitation_id>/accept", methods=["POST"])
@login_required
def accept_invitation(tournament_url, invitation_id):
    """Accept a pending player registration."""
    if current_user.__class__.__name__ != "Team":
        return (
            jsonify({"success": False, "error": "Only teams can accept invitations"}),
            403,
        )

    player_registration = PlayerRegistration.query.filter_by(
        id=invitation_id,
        event=tournament_url,
        team=current_user.id,
        status=RegistrationStatus.PENDING_TEAM_APPROVAL,
    ).first_or_404()

    player_registration.status = RegistrationStatus.CONFIRMED
    db.session.commit()
    return (
        jsonify(
            {"success": True, "message": "Player approved! They are now on your team."}
        ),
        200,
    )


@bp.route("/<tournament_url>/invitation/<int:invitation_id>/decline", methods=["POST"])
@login_required
def decline_invitation(tournament_url, invitation_id):
    """Decline a pending player registration."""
    if current_user.__class__.__name__ != "Team":
        return (
            jsonify({"success": False, "error": "Only teams can decline invitations"}),
            403,
        )

    player_registration = PlayerRegistration.query.filter_by(
        id=invitation_id,
        event=tournament_url,
        team=current_user.id,
        status=RegistrationStatus.PENDING_TEAM_APPROVAL,
    ).first_or_404()

    player_registration.status = RegistrationStatus.REJECTED
    db.session.commit()
    return jsonify({"success": True, "message": "Player request declined"}), 200
