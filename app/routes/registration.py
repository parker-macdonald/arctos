"""Team and player registration routes.

Hosts the ``registration`` blueprint.

Endpoints cover the full
register / cancel / re-register lifecycle for both teams and players
and for both standalone tournaments and league-scoped events.

The multi-model workflow itself lives in
``app.services.registration_service``; this file is the thin HTTP
layer in front of it.
"""

from flask import Blueprint, g, request, jsonify
from flask_login import login_required, current_user  # type: ignore[import-untyped]
from datetime import datetime
from models import (
    Tournament,
    TeamRegistration,
    PlayerRegistration,
    db,
)
from app.domain.enums import RegistrationStatus
from app.services._common import current_user_type
from app.services.registration_service import RegistrationService
from app.services.permission_service import PermissionService
from app.utils.decorators import require_json_body, require_tournament_organizer
from app.utils.user_helpers import is_player, is_team
from app.utils.result_helpers import json_from_result
from app.utils.datetime_helpers import now_utc_naive

bp = Blueprint("registration", __name__, url_prefix="/_api")


@bp.route("/<tournament_url>/register-team", methods=["POST"])
@login_required
def register_team_for_tournament(tournament_url: str):
    """Register the current team account for a tournament.

    ``POST /_api/<tournament_url>/register-team``

    Only :class:`~app.models.user.Team` accounts may call this endpoint.
    Delegates to :class:`~app.services.registration_service.RegistrationService`.

    Args:
        tournament_url: Tournament URL slug from the path.

    Form Data:
        pseudonym (str): Team display name for this tournament.

    Returns:
        JSON ``{"success": true, "message": "..."}`` on success, or
        ``{"success": false, "error": "..."}`` with HTTP 400/403 on failure.
    """
    if not is_team(current_user):
        return (
            jsonify({"success": False, "error": "Only teams can register for tournaments"}),
            403,
        )

    res = RegistrationService.register_team(tournament_url, current_user.id, request.form.get("pseudonym", ""))
    return json_from_result(
        res,
        ok_to_payload=lambda _: {"message": "Team registration successful!"},
        err_status_code=400,
    )


@bp.route("/<tournament_url>/register-player", methods=["POST"])
@login_required
def register_player_for_tournament(tournament_url: str):
    """Register the current player account for a tournament.

    ``POST /_api/<tournament_url>/register-player``

    Only :class:`~app.models.user.Player` accounts may call this endpoint.
    When a *team* is supplied the registration starts as
    ``PENDING_TEAM_APPROVAL``; without a team it is immediately
    ``CONFIRMED``.

    Args:
        tournament_url: Tournament URL slug from the path.

    Form Data:
        team (str | None): Team ID to register under, or empty for unattached.
        jersey_number (str): Jersey number for this tournament.
        jersey_name (str): Name to print on the jersey.
        waiver_legal_name_signature (str): Player's legal-name signature.

    Returns:
        JSON ``{"success": true, "message": "..."}`` on success, or
        ``{"success": false, "error": "..."}`` with HTTP 400/403 on failure.
    """
    if not is_player(current_user):
        return (
            jsonify({"success": False, "error": "Only players can register for tournaments"}),
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
    return json_from_result(
        res,
        ok_to_payload=lambda _: {
            "message": (
                "Registration submitted! The team will need to approve your request."
                if team_id
                else "Player registration successful! You are now registered for the tournament."
            )
        },
        err_status_code=400,
    )


@bp.route("/<tournament_url>/deregister-team", methods=["POST"])
@login_required
def deregister_team_from_tournament(tournament_url: str):
    """Cancel the current team's registration for a tournament.

    ``POST /_api/<tournament_url>/deregister-team``

    Only :class:`~app.models.user.Team` accounts may call this endpoint.

    Args:
        tournament_url: Tournament URL slug from the path.

    Returns:
        JSON success or error body.
    """
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
    return json_from_result(
        res,
        ok_to_payload=lambda _: {"message": "Team successfully deregistered from tournament"},
        err_status_code=400,
    )


@bp.route("/<tournament_url>/deregister-player", methods=["POST"])
@login_required
def deregister_player_from_tournament(tournament_url: str):
    """Cancel the current player's registration for a tournament.

    ``POST /_api/<tournament_url>/deregister-player``

    Only :class:`~app.models.user.Player` accounts may call this endpoint.

    Args:
        tournament_url: Tournament URL slug from the path.

    Returns:
        JSON success or error body.
    """
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
    return json_from_result(
        res,
        ok_to_payload=lambda _: {"message": "Player successfully deregistered from tournament"},
        err_status_code=400,
    )


@bp.route("/<tournament_url>/mark-team-paid", methods=["POST"])
@require_tournament_organizer("Only tournament organizers can perform this action")
def mark_team_paid(tournament_url: str):
    """Update payment status for a team registration (TO only).

    ``POST /_api/<tournament_url>/mark-team-paid``

    Requires the caller to be a Tournament Organiser for the event.

    Args:
        tournament_url: Tournament URL slug from the path.

    Form Data:
        registration_id (int): Primary key of the
            :class:`~app.models.registration.TeamRegistration`.
        paid (str): ``"on"`` to mark paid, any other value to mark unpaid.
        amount_paid (float): Total amount paid.
        payment_method (str): Payment method description.
        payment_reference (str): Transaction reference number.
        payment_notes (str): Free-text notes.

    Returns:
        JSON ``{"success": true, "message": "..."}`` on success, or 403/404.
    """
    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()

    reg_id = request.form.get("registration_id")
    paid = request.form.get("paid") == "on"
    amount_paid = float(request.form.get("amount_paid") or 0)
    payment_method = request.form.get("payment_method", "")
    payment_reference = request.form.get("payment_reference", "")
    payment_notes = request.form.get("payment_notes", "")

    reg = TeamRegistration.query.filter_by(id=reg_id, event=tournament_url).first_or_404()
    reg.paid = paid
    reg.amount_paid = amount_paid
    reg.payment_method = payment_method
    reg.payment_reference = payment_reference
    reg.payment_notes = payment_notes
    reg.paid_at = now_utc_naive() if paid else None
    db.session.commit()
    return jsonify({"success": True, "message": "Team payment updated"}), 200


@bp.route("/<tournament_url>/mark-player-paid", methods=["POST"])
@require_tournament_organizer("Only tournament organizers can perform this action")
def mark_player_paid(tournament_url: str):
    """Update payment status for a player registration (TO only).

    ``POST /_api/<tournament_url>/mark-player-paid``

    Requires the caller to be a Tournament Organiser for the event.

    Args:
        tournament_url: Tournament URL slug from the path.

    Form Data:
        registration_id (int): Primary key of the
            :class:`~app.models.registration.PlayerRegistration`.
        paid (str): ``"on"`` to mark paid, any other value to mark unpaid.
        amount_paid (float): Total amount paid.
        payment_method (str): Payment method description.
        payment_reference (str): Transaction reference number.
        payment_notes (str): Free-text notes.

    Returns:
        JSON ``{"success": true, "message": "..."}`` on success, or 403/404.
    """
    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()

    reg_id = request.form.get("registration_id")
    paid = request.form.get("paid") == "on"
    amount_paid = float(request.form.get("amount_paid") or 0)
    payment_method = request.form.get("payment_method", "")
    payment_reference = request.form.get("payment_reference", "")
    payment_notes = request.form.get("payment_notes", "")

    reg = PlayerRegistration.query.filter_by(id=reg_id, event=tournament_url).first_or_404()
    reg.paid = paid
    reg.amount_paid = amount_paid
    reg.payment_method = payment_method
    reg.payment_reference = payment_reference
    reg.payment_notes = payment_notes
    reg.paid_at = now_utc_naive() if paid else None
    db.session.commit()
    return jsonify({"success": True, "message": "Player payment updated"}), 200


@bp.route("/<tournament_url>/deregister-any-team", methods=["POST"])
@require_tournament_organizer("Only tournament organizers can perform this action")
def deregister_any_team(tournament_url: str):
    """Forcibly cancel a team's registration (TO only).

    ``POST /_api/<tournament_url>/deregister-any-team``

    Cancels the team registration and all associated player registrations.
    Requires the caller to be a Tournament Organiser for the event.

    Args:
        tournament_url: Tournament URL slug from the path.

    Form Data:
        team_id (str): ID of the team to deregister.

    Returns:
        JSON success or error body.
    """
    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()

    team_id = request.form.get("team_id")
    if not team_id:
        return jsonify({"success": False, "error": "Team ID is required"}), 400

    team_registration = TeamRegistration.query.filter_by(
        event=tournament_url, team=team_id, status=RegistrationStatus.CONFIRMED
    ).first()

    if team_registration:
        team_registration.status = RegistrationStatus.CANCELLED

        affected_player_ids = [
            r.player for r in PlayerRegistration.query.filter_by(event=tournament_url, team=team_id).all()
        ]

        PlayerRegistration.query.filter_by(event=tournament_url, team=team_id).update(
            {"status": RegistrationStatus.CANCELLED}
        )

        from app.services.sidecomp_service import SideCompService

        for pid in affected_player_ids:
            SideCompService.cancel_player_registrations_in_event(tournament_url, pid)

        db.session.commit()
        return (
            jsonify({"success": True, "message": "Team successfully deregistered"}),
            200,
        )
    else:
        return (
            jsonify({"success": False, "error": "Team not found or already deregistered"}),
            404,
        )


@bp.route("/<tournament_url>/deregister-any-player", methods=["POST"])
@require_tournament_organizer("Only tournament organizers can perform this action")
def deregister_any_player(tournament_url: str):
    """Forcibly cancel a player's registration (TO only).

    ``POST /_api/<tournament_url>/deregister-any-player``

    Cancels the player's registration regardless of its current status.
    Requires the caller to be a Tournament Organiser for the event.

    Args:
        tournament_url: Tournament URL slug from the path.

    Form Data:
        player_id (str): ID of the player to deregister.

    Returns:
        JSON success or error body.
    """
    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()

    player_id = request.form.get("player_id")
    if not player_id:
        return jsonify({"success": False, "error": "Player ID is required"}), 400

    player_registration = (
        PlayerRegistration.query.filter_by(event=tournament_url, player=player_id)
        .filter(PlayerRegistration.status.in_([RegistrationStatus.PENDING_TEAM_APPROVAL, RegistrationStatus.CONFIRMED]))
        .first()
    )

    if player_registration:
        player_registration.status = RegistrationStatus.CANCELLED

        from app.services.sidecomp_service import SideCompService

        SideCompService.cancel_player_registrations_in_event(tournament_url, player_id)

        db.session.commit()
        return (
            jsonify({"success": True, "message": "Player successfully deregistered"}),
            200,
        )
    else:
        return (
            jsonify({"success": False, "error": "Player not found or already deregistered"}),
            404,
        )


@bp.route("/<tournament_url>/invitation/<int:invitation_id>/accept", methods=["POST"])
@login_required
def accept_invitation(tournament_url: str, invitation_id: int):
    """Accept a player's pending registration request.

    ``POST /_api/<tournament_url>/invitation/<invitation_id>/accept``

    Only :class:`~app.models.user.Team` accounts may call this endpoint.
    Transitions the player's registration from ``PENDING_TEAM_APPROVAL`` to
    ``CONFIRMED``.

    Args:
        tournament_url: Tournament URL slug from the path.
        invitation_id: Primary key of the
            :class:`~app.models.registration.PlayerRegistration` to approve.

    Returns:
        JSON success or 403/404 error body.
    """
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
        jsonify({"success": True, "message": "Player approved! They are now on your team."}),
        200,
    )


@bp.route("/<tournament_url>/invitation/<int:invitation_id>/decline", methods=["POST"])
@login_required
def decline_invitation(tournament_url: str, invitation_id: int):
    """Decline a player's pending registration request.

    ``POST /_api/<tournament_url>/invitation/<invitation_id>/decline``

    Only :class:`~app.models.user.Team` accounts may call this endpoint.
    Transitions the player's registration from ``PENDING_TEAM_APPROVAL`` to
    ``REJECTED``.

    Args:
        tournament_url: Tournament URL slug from the path.
        invitation_id: Primary key of the
            :class:`~app.models.registration.PlayerRegistration` to reject.

    Returns:
        JSON success or 403/404 error body.
    """
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


@bp.route("/<tournament_url>/register-player-as-to", methods=["POST"])
@login_required
@require_json_body()
def register_player_as_to(tournament_url: str):
    """Tournament-organizer-driven player registration.

    ``POST /_api/<tournament_url>/register-player-as-to``

    The caller must be a TO of this tournament (enforced in the service
    layer). Registers an existing player to the tournament with an auto-confirmed,
    fully-paid registration.

    Args:
        tournament_url: Tournament URL slug from the path.

    Request JSON:
        player_id (str): ID of the existing player to register on behalf. Required.
        team (str | None): Team ID to register under, or null/omitted for
            unaffiliated.
        jersey_number (str): Jersey number; defaults to ``"0"`` when blank.
        jersey_name (str): Jersey name; defaults to ``"N/A"`` when blank.
        waiver_legal_name_signature (str): Player's legal-name signature
            (typed by the TO on the player's behalf). Required when the
            tournament has a waiver configured.

    Returns:
        ``200`` with the resolved registration fields on success, or
        ``{success: false, error}`` with an appropriate status on failure.
    """
    data = g.json_body

    player_id = (data.get("player_id") or "").strip()
    if not player_id:
        return jsonify({"success": False, "error": "player_id is required"}), 400

    res = RegistrationService.register_player_as_to(
        tournament_url,
        actor_user_id=current_user.id,
        actor_user_type=current_user_type(),
        player_id=player_id,
        team_id=(data.get("team") or None),
        jersey_number=data.get("jersey_number", ""),
        jersey_name=data.get("jersey_name", ""),
        waiver_legal_name_signature=data.get("waiver_legal_name_signature", ""),
    )
    from models import Player

    def _checkin_payload(reg):
        player = Player.query.get(reg.player)
        return {
            "message": "Player registered",
            "player_id": reg.player,
            "player_name": player.name if player else reg.player,
            "team": reg.team,
            "jersey_number": reg.jersey_number,
            "jersey_name": reg.jersey_name,
        }

    return json_from_result(res, ok_to_payload=_checkin_payload)


@bp.route("/<tournament_url>/register-team-as-to", methods=["POST"])
@login_required
@require_json_body()
def register_team_as_to(tournament_url: str):
    """Tournament-organizer-driven team registration.

    ``POST /_api/<tournament_url>/register-team-as-to``

    The caller must be a TO of this tournament (enforced in the service
    layer). Adds an existing team to the tournament with an auto-confirmed,
    fully-paid registration.

    Args:
        tournament_url: Tournament URL slug from the path.

    Request JSON:
        team_id (str): ID of the existing team to register. Required.
        pseudonym (str): Per-tournament team display name. Optional;
            defaults to ``team.name`` when blank.

    Returns:
        ``200`` with the resolved registration fields on success, or
        ``{success: false, error}`` with an appropriate status on failure.
    """
    data = g.json_body

    team_id = (data.get("team_id") or "").strip()
    if not team_id:
        return jsonify({"success": False, "error": "team_id is required"}), 400

    res = RegistrationService.register_team_as_to(
        tournament_url,
        actor_user_id=current_user.id,
        actor_user_type=current_user_type(),
        team_id=team_id,
        pseudonym=data.get("pseudonym", ""),
    )
    from models import Team

    def _checkin_team_payload(reg):
        team = Team.query.get(reg.team)
        return {
            "message": "Team registered",
            "team_id": reg.team,
            "team_name": team.name if team else reg.team,
            "pseudonym": reg.pseudonym,
        }

    return json_from_result(res, ok_to_payload=_checkin_team_payload)
