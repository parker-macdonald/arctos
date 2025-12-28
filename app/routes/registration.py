"""
Tournament registration management routes.
"""

from flask import Blueprint, render_template, request, redirect, flash
from flask_login import login_required, current_user
from datetime import datetime
from models import (
    Tournament,
    TeamRegistration,
    PlayerRegistration,
    Team,
    Player,
    TO,
    db,
)
from app.utils.decorators import require_tournament_organizer
from app.services.registration_service import RegistrationService
from app.utils.user_helpers import is_player, is_team
from app.error_values import Ok, Err
from app.utils.result_helpers import public_error_message

bp = Blueprint("registration", __name__)


@bp.route("/<tournament_url>/register-team", methods=["POST"])
@login_required
def register_team_for_tournament(tournament_url):
    """Register a team for a tournament."""
    if not is_team(current_user):
        flash("Only teams can register for tournaments", "error")
        return redirect(f"/{tournament_url}/register")

    res = RegistrationService.register_team(
        tournament_url, current_user.id, request.form.get("pseudonym", "")
    )
    match res:
        case Ok(_):
            flash("Team registration successful!", "success")
            return redirect(f"/{tournament_url}")
        case Err(err):
            flash(public_error_message(err), "error")
            return redirect(f"/{tournament_url}/register")


@bp.route("/<tournament_url>/register-player", methods=["POST"])
@login_required
def register_player_for_tournament(tournament_url):
    """Register a player for a tournament."""
    if not is_player(current_user):
        flash("Only players can register for tournaments", "error")
        return redirect(f"/{tournament_url}/register")

    team_id = request.form.get("team", "") or None
    res = RegistrationService.register_player(
        tournament_url,
        current_user.id,
        team_id,
        jersey_number=request.form.get("jersey_number", ""),
        jersey_name=request.form.get("jersey_name", ""),
    )
    match res:
        case Ok(_):
            if team_id:
                flash(
                    "Registration submitted! The team will need to approve your request.",
                    "success",
                )
            else:
                flash(
                    "Player registration successful! You are now registered for the tournament.",
                    "success",
                )
            return redirect(f"/{tournament_url}")
        case Err(err):
            flash(public_error_message(err), "error")
            return redirect(f"/{tournament_url}/register")


@bp.route("/<tournament_url>/deregister-team", methods=["POST"])
@login_required
def deregister_team_from_tournament(tournament_url):
    """Deregister a team from a tournament."""
    if not is_team(current_user):
        flash("Only teams can deregister from tournaments", "error")
        return redirect(f"/{tournament_url}")

    res = RegistrationService.deregister_team(tournament_url, current_user.id)
    match res:
        case Ok(_):
            flash("Team successfully deregistered from tournament", "success")
            return redirect(f"/{tournament_url}")
        case Err(err):
            flash(public_error_message(err), "error")
            return redirect(f"/{tournament_url}")


@bp.route("/<tournament_url>/deregister-player", methods=["POST"])
@login_required
def deregister_player_from_tournament(tournament_url):
    """Deregister a player from a tournament."""
    if not is_player(current_user):
        flash("Only players can deregister from tournaments", "error")
        return redirect(f"/{tournament_url}")

    res = RegistrationService.deregister_player(tournament_url, current_user.id)
    match res:
        case Ok(_):
            flash("Player successfully deregistered from tournament", "success")
            return redirect(f"/{tournament_url}")
        case Err(err):
            flash(public_error_message(err), "error")
            return redirect(f"/{tournament_url}")


@bp.route("/<tournament_url>/manage")
@require_tournament_organizer()
def tournament_manage(tournament_url):
    """Tournament registration management page."""
    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()

    search_query = (request.args.get("search") or "").strip()
    search_type = (request.args.get("type") or "both").lower()

    team_registrations = (
        TeamRegistration.query.filter_by(event=tournament_url)
        .filter(TeamRegistration.status != "CANCELLED")
        .all()
    )
    teams_with_registrations = []
    for team_reg in team_registrations:
        team = Team.query.get(team_reg.team)
        if team:
            teams_with_registrations.append({"registration": team_reg, "team": team})

    player_registrations = (
        PlayerRegistration.query.filter_by(event=tournament_url)
        .filter(PlayerRegistration.status != "CANCELLED")
        .all()
    )

    players_with_registrations = []
    for player_reg in player_registrations:
        player = Player.query.get(player_reg.player)
        team = Team.query.get(player_reg.team) if player_reg.team else None
        if player:
            players_with_registrations.append(
                {"registration": player_reg, "player": player, "team": team}
            )

    if search_query:
        q = search_query.lower()
        if search_type in ("both", "teams"):
            teams_with_registrations = [
                t
                for t in teams_with_registrations
                if (
                    (t["team"].name or "").lower().find(q) != -1
                    or (t["registration"].pseudonym or "").lower().find(q) != -1
                )
            ]
        else:
            teams_with_registrations = []

        if search_type in ("both", "players"):
            players_with_registrations = [
                p
                for p in players_with_registrations
                if (
                    (p["player"].name or "").lower().find(q) != -1
                    or (p["registration"].jersey_name or "").lower().find(q) != -1
                )
            ]
        else:
            players_with_registrations = []

    return render_template(
        "tournament_manage.html",
        tournament=tournament,
        team_registrations=teams_with_registrations,
        players_with_registrations=players_with_registrations,
        search_query=search_query,
        search_type=search_type,
    )


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
        flash("Only tournament organizers can perform this action", "error")
        return redirect(f"/{tournament_url}/manage")

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
    reg.paid_at = datetime.utcnow() if paid else None
    db.session.commit()
    flash("Team payment updated", "success")
    return redirect(f"/{tournament_url}/manage")


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
        flash("Only tournament organizers can perform this action", "error")
        return redirect(f"/{tournament_url}/manage")

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
    reg.paid_at = datetime.utcnow() if paid else None
    db.session.commit()
    flash("Player payment updated", "success")
    return redirect(f"/{tournament_url}/manage")


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
        flash("Only tournament organizers can perform this action", "error")
        return redirect(f"/{tournament_url}")

    team_id = request.form.get("team_id")
    if not team_id:
        flash("Team ID is required", "error")
        return redirect(f"/{tournament_url}/manage")

    team_registration = TeamRegistration.query.filter_by(
        event=tournament_url, team=team_id, status="CONFIRMED"
    ).first()

    if team_registration:
        team_registration.status = "CANCELLED"

        PlayerRegistration.query.filter_by(event=tournament_url, team=team_id).update(
            {"status": "CANCELLED"}
        )

        db.session.commit()
        flash("Team successfully deregistered", "success")
    else:
        flash("Team not found or already deregistered", "error")

    return redirect(f"/{tournament_url}/manage")


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
        flash("Only tournament organizers can perform this action", "error")
        return redirect(f"/{tournament_url}")

    player_id = request.form.get("player_id")
    if not player_id:
        flash("Player ID is required", "error")
        return redirect(f"/{tournament_url}/manage")

    player_registration = (
        PlayerRegistration.query.filter_by(event=tournament_url, player=player_id)
        .filter(PlayerRegistration.status.in_(["PENDING_TEAM_APPROVAL", "CONFIRMED"]))
        .first()
    )

    if player_registration:
        player_registration.status = "CANCELLED"

        db.session.commit()
        flash("Player successfully deregistered", "success")
    else:
        flash("Player not found or already deregistered", "error")

    return redirect(f"/{tournament_url}/manage")


@bp.route("/<tournament_url>/edit-team-registration")
@login_required
def edit_team_registration(tournament_url):
    """Edit team registration page."""
    if current_user.__class__.__name__ != "Team":
        flash("Only teams can edit their registration", "error")
        return redirect(f"/{tournament_url}")

    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()

    team_registration = TeamRegistration.query.filter_by(
        event=tournament_url, team=current_user.id, status="CONFIRMED"
    ).first()

    if not team_registration:
        flash("You are not registered for this tournament", "error")
        return redirect(f"/{tournament_url}")

    return render_template(
        "edit_team_registration.html",
        tournament=tournament,
        registration=team_registration,
    )


@bp.route("/<tournament_url>/edit-team-registration", methods=["POST"])
@login_required
def update_team_registration(tournament_url):
    """Update team registration."""
    if current_user.__class__.__name__ != "Team":
        flash("Only teams can edit their registration", "error")
        return redirect(f"/{tournament_url}")

    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()

    if not tournament.registration_open:
        flash("Registration changes are locked", "error")
        return redirect(f"/{tournament_url}")

    team_registration = TeamRegistration.query.filter_by(
        event=tournament_url, team=current_user.id, status="CONFIRMED"
    ).first()

    if not team_registration:
        flash("You are not registered for this tournament", "error")
        return redirect(f"/{tournament_url}")

    # Validate pseudonym doesn't contain "::"
    pseudonym = request.form.get("pseudonym", "").strip()
    if "::" in pseudonym:
        flash('Team pseudonyms cannot contain "::"', "error")
        return redirect(f"/{tournament_url}/edit-team-registration")

    if not pseudonym:
        flash("Team name is required", "error")
        return redirect(f"/{tournament_url}/edit-team-registration")

    team_registration.pseudonym = pseudonym
    db.session.commit()

    flash("Team registration updated successfully!", "success")
    return redirect(f"/{tournament_url}")


@bp.route("/<tournament_url>/edit-player-registration")
@login_required
def edit_player_registration(tournament_url):
    """Edit player registration page."""
    if current_user.__class__.__name__ != "Player":
        flash("Only players can edit their registration", "error")
        return redirect(f"/{tournament_url}")

    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()

    player_registration = (
        PlayerRegistration.query.filter_by(event=tournament_url, player=current_user.id)
        .filter(PlayerRegistration.status.in_(["PENDING_TEAM_APPROVAL", "CONFIRMED"]))
        .first()
    )

    if not player_registration:
        flash("You are not registered for this tournament", "error")
        return redirect(f"/{tournament_url}")

    # Get all registered teams for the dropdown
    registered_teams = TeamRegistration.query.filter_by(
        event=tournament_url, status="CONFIRMED"
    ).all()

    team_data = []
    for reg in registered_teams:
        team = Team.query.get(reg.team)
        if team:
            team_data.append(
                {"team": team, "pseudonym": reg.pseudonym, "registration": reg}
            )

    # Get current team registration if player is on a team
    current_team_reg = None
    if player_registration.team:
        current_team_reg = TeamRegistration.query.filter_by(
            event=tournament_url, team=player_registration.team, status="CONFIRMED"
        ).first()

    return render_template(
        "edit_player_registration.html",
        tournament=tournament,
        registration=player_registration,
        registered_teams=team_data,
        current_team_reg=current_team_reg,
    )


@bp.route("/<tournament_url>/edit-player-registration", methods=["POST"])
@login_required
def update_player_registration(tournament_url):
    """Update player registration."""
    if current_user.__class__.__name__ != "Player":
        flash("Only players can edit their registration", "error")
        return redirect(f"/{tournament_url}")

    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()

    if not tournament.registration_open:
        flash("Registration changes are locked", "error")
        return redirect(f"/{tournament_url}")

    player_registration = (
        PlayerRegistration.query.filter_by(event=tournament_url, player=current_user.id)
        .filter(PlayerRegistration.status.in_(["PENDING_TEAM_APPROVAL", "CONFIRMED"]))
        .first()
    )

    if not player_registration:
        flash("You are not registered for this tournament", "error")
        return redirect(f"/{tournament_url}")

    old_team_id = player_registration.team
    new_team_id = request.form.get("team", "") or None

    # Update jersey name and number
    player_registration.jersey_name = request.form.get("jersey_name", "").strip()
    player_registration.jersey_number = request.form.get("jersey_number", "").strip()

    # If team changed, require re-approval
    if old_team_id != new_team_id:
        # Update team
        player_registration.team = new_team_id

        # If joining a new team, set status to pending team approval
        if new_team_id:
            player_registration.status = "PENDING_TEAM_APPROVAL"
            flash("Team changed. Your new team must approve your request.", "warning")
        else:
            # No team selected - confirmed immediately
            player_registration.status = "CONFIRMED"
            flash("Registration updated successfully!", "success")
    else:
        # Team didn't change, just update other fields
        flash("Registration updated successfully!", "success")

    db.session.commit()
    return redirect(f"/{tournament_url}")


@bp.route("/<tournament_url>/invitations")
@login_required
def tournament_invitations(tournament_url):
    """Team roster management page (pending player registrations + roster)."""
    if current_user.__class__.__name__ != "Team":
        flash("Only teams can view invitations", "error")
        return redirect(f"/{tournament_url}")

    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()

    team_registration = TeamRegistration.query.filter_by(
        event=tournament_url, team=current_user.id, status="CONFIRMED"
    ).first()

    if not team_registration:
        flash("You are not registered for this tournament", "error")
        return redirect(f"/{tournament_url}")

    pending_regs = PlayerRegistration.query.filter_by(
        event=tournament_url, team=current_user.id, status="PENDING_TEAM_APPROVAL"
    ).all()

    pending_with_players = []
    for reg in pending_regs:
        player = Player.query.get(reg.player)
        if player:
            pending_with_players.append(
                {
                    "registration": reg,
                    "player": player,
                }
            )

    # Calculate current team size (confirmed players on this team)
    current_team_size = PlayerRegistration.query.filter_by(
        event=tournament_url, team=current_user.id, status="CONFIRMED"
    ).count()

    # Get all player registrations for this team (all statuses)
    all_player_registrations = PlayerRegistration.query.filter_by(
        event=tournament_url, team=current_user.id
    ).all()

    team_roster = []
    for reg in all_player_registrations:
        player = Player.query.get(reg.player)
        if player:
            team_roster.append({"player": player, "registration": reg})

    return render_template(
        "tournament_invitations.html",
        tournament=tournament,
        team_registration=team_registration,
        invitations=pending_with_players,
        current_team_size=current_team_size,
        team_roster=team_roster,
    )


@bp.route("/<tournament_url>/invitation/<int:invitation_id>/accept", methods=["POST"])
@login_required
def accept_invitation(tournament_url, invitation_id):
    """Accept a pending player registration (legacy URL kept for compatibility)."""
    if current_user.__class__.__name__ != "Team":
        flash("Only teams can accept invitations", "error")
        return redirect(f"/{tournament_url}/invitations")

    player_registration = PlayerRegistration.query.filter_by(
        id=invitation_id,
        event=tournament_url,
        team=current_user.id,
        status="PENDING_TEAM_APPROVAL",
    ).first_or_404()

    player_registration.status = "CONFIRMED"
    db.session.commit()
    flash("Player approved! They are now on your team.", "success")

    return redirect(f"/{tournament_url}/invitations")


@bp.route("/<tournament_url>/invitation/<int:invitation_id>/decline", methods=["POST"])
@login_required
def decline_invitation(tournament_url, invitation_id):
    """Decline a pending player registration (legacy URL kept for compatibility)."""
    if current_user.__class__.__name__ != "Team":
        flash("Only teams can decline invitations", "error")
        return redirect(f"/{tournament_url}/invitations")

    player_registration = PlayerRegistration.query.filter_by(
        id=invitation_id,
        event=tournament_url,
        team=current_user.id,
        status="PENDING_TEAM_APPROVAL",
    ).first_or_404()

    player_registration.status = "REJECTED"
    db.session.commit()
    flash("Player request declined", "info")
    return redirect(f"/{tournament_url}/invitations")
