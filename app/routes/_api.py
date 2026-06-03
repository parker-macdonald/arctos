"""Internal JSON API for the Dioxus SPA.

Hosts the ``_api`` blueprint - the catch-all for endpoints that don't
have a more specific home (tournament listing, match detail, points
CRUD, schedule queries, rosters, head-ref permissions, photos, profile
updates, search, ...).
"""

from flask import Blueprint, request, jsonify
from flask_login import current_user, login_required
from app.services._common import Scope
from app.services.permission_service import PermissionService
from app.utils.helpers import (
    get_registrable_config,
)
from app.serializers.league_serializer import require_league
from app.serializers.registration_serializer import player_reg_waiver_api
from app.utils.name_validation import team_pseudonym_char_error
from app.utils.datetime_helpers import now_utc_naive
from app.utils.user_helpers import is_player, is_team
from app.domain.enums import (
    RegistrationStatus,
)
from models import (
    Tournament,
    TeamRegistration,
    PlayerRegistration,
    db,
)

bp = Blueprint("_api", __name__, url_prefix="/_api")


def _dt_iso(dt) -> str | None:
    """Serialise a datetime-like value to an ISO-8601 string.

    Args:
        dt: A :class:`~datetime.datetime` instance or any object with an
            ``isoformat()`` method, or ``None``.

    Returns:
        ISO-8601 string when *dt* is non-null, otherwise ``None``.
    """
    if dt is None:
        return None
    if hasattr(dt, "isoformat"):
        return dt.isoformat()
    return str(dt)


@login_required
def league_register_team(league_url):
    """Register a team for a league.

    Form Data:
        pseudonym (str): Team display name for this league.
        shortname (str, optional): Short alias (<= 12 chars) used in
            space-constrained UI. Blank/missing stores ``NULL``.
    """
    from app.services.registration_service import RegistrationService
    from app.utils.result_helpers import json_from_result

    if not is_team(current_user):
        return jsonify({"success": False, "error": "Only teams can register"}), 403
    league, err = require_league(league_url)
    if err:
        return jsonify({"error": "Not found" if err == 404 else "Forbidden"}), err
    res = RegistrationService.register_team(
        Scope.league(league.url),
        current_user.id,
        request.form.get("pseudonym", ""),
        shortname=request.form.get("shortname", "") or None,
    )
    return json_from_result(
        res,
        ok_to_payload=lambda _: {"message": "Team registration successful!"},
        err_status_code=400,
    )


@login_required
def league_register_player(league_url):
    """Register a player for a league."""
    from app.services.registration_service import RegistrationService
    from app.utils.result_helpers import json_from_result

    if not is_player(current_user):
        return jsonify({"success": False, "error": "Only players can register"}), 403
    league, err = require_league(league_url)
    if err:
        return jsonify({"error": "Not found" if err == 404 else "Forbidden"}), err
    team_id = request.form.get("team", "") or None
    msg = (
        "Registration submitted! The team will need to approve your request."
        if team_id
        else "Player registration successful!"
    )
    res = RegistrationService.register_player(
        Scope.league(league.url),
        current_user.id,
        team_id,
        jersey_number=request.form.get("jersey_number", ""),
        jersey_name=request.form.get("jersey_name", ""),
        waiver_legal_name_signature=request.form.get("waiver_legal_name_signature", ""),
    )
    return json_from_result(
        res,
        ok_to_payload=lambda _: {"message": msg},
        err_status_code=400,
    )


@login_required
def league_deregister_team(league_url):
    """Deregister a team from a league."""
    from app.services.registration_service import RegistrationService
    from app.utils.result_helpers import json_from_result

    if not is_team(current_user):
        return jsonify({"success": False, "error": "Only teams can deregister"}), 403
    league, err = require_league(league_url)
    if err:
        return jsonify({"error": "Not found" if err == 404 else "Forbidden"}), err
    res = RegistrationService.deregister_team(Scope.league(league.url), current_user.id)
    return json_from_result(
        res,
        ok_to_payload=lambda _: {"message": "Team deregistered"},
        err_status_code=400,
    )


@login_required
def league_deregister_player(league_url):
    """Deregister a player from a league."""
    from app.services.registration_service import RegistrationService
    from app.utils.result_helpers import json_from_result

    if not is_player(current_user):
        return jsonify({"success": False, "error": "Only players can deregister"}), 403
    league, err = require_league(league_url)
    if err:
        return jsonify({"error": "Not found" if err == 404 else "Forbidden"}), err
    res = RegistrationService.deregister_player(Scope.league(league.url), current_user.id)
    return json_from_result(
        res,
        ok_to_payload=lambda _: {"message": "Player deregistered"},
        err_status_code=400,
    )


@login_required
def get_my_player_registration_league(league_url):
    """Get current player's registration for this league."""
    if not is_player(current_user):
        return jsonify({"error": "Only players have player registrations"}), 400

    from app.services.registration_resolver import (
        player_registration_for_tournament,
        team_registration_for_tournament,
    )

    league, err = require_league(league_url)
    if err:
        return jsonify({"error": "Not found" if err == 404 else "Forbidden"}), err

    class LeagueContext:
        def __init__(self, league):
            self.league_id = league.url
            self.url = None

    ctx = LeagueContext(league)
    reg = player_registration_for_tournament(ctx, current_user.id)

    if not reg:
        return jsonify({"error": "Not registered"}), 404

    current_team = None
    if reg.team:
        team_reg = team_registration_for_tournament(ctx, reg.team)
        if team_reg:
            current_team = {
                "id": reg.team,
                "pseudonym": team_reg.pseudonym,
                "shortname": team_reg.shortname,
            }

    rc = league.registrable_config
    w = player_reg_waiver_api(reg, rc)
    return jsonify(
        {
            "registration": {
                "id": reg.id,
                "jersey_name": reg.jersey_name,
                "jersey_number": reg.jersey_number,
                "team": reg.team,
                "status": (reg.status.value if hasattr(reg.status, "value") else str(reg.status)),
            },
            "current_team": current_team,
            "waiver_required": w["waiver_required"],
            "waiver_filepath": w["waiver_filepath"],
            "waiver_sha256": w["waiver_sha256"],
            "waiver_signature_valid": w["waiver_signature_valid"],
            "waiver_legal_name_signature": w["waiver_legal_name_signature"],
        }
    )


@login_required
def update_my_player_registration_league(league_url):
    """Update current player's registration for this league."""
    from app.services.registration_resolver import player_registration_for_tournament

    if not is_player(current_user):
        return jsonify({"error": "Only players can edit their registration"}), 400

    league, err = require_league(league_url)
    if err:
        return jsonify({"error": "Not found" if err == 404 else "Forbidden"}), err

    if not league.registrable_config or not league.registrable_config.player_registration_open:
        return jsonify({"error": "Registration changes are locked"}), 403

    class LeagueContext:
        def __init__(self, league):
            self.league_id = league.url
            self.url = None

    ctx = LeagueContext(league)
    reg = player_registration_for_tournament(ctx, current_user.id)

    if not reg:
        return jsonify({"error": "Not registered"}), 404

    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400

    if "jersey_name" in data:
        reg.jersey_name = data["jersey_name"]
    if "jersey_number" in data:
        reg.jersey_number = data["jersey_number"]

    if "team" in data:
        new_team_id = data["team"] or None
        if reg.team != new_team_id:
            reg.team = new_team_id
            if new_team_id:
                reg.status = RegistrationStatus.PENDING_TEAM_APPROVAL
            else:
                reg.status = RegistrationStatus.CONFIRMED

    if "waiver_legal_name_signature" in data and data["waiver_legal_name_signature"]:
        rc = league.registrable_config
        sig = (data.get("waiver_legal_name_signature") or "").strip()
        if rc and getattr(rc, "waiver_filepath", None) and sig:
            sha_cur = getattr(rc, "waiver_sha256", None)
            if sha_cur:
                now = now_utc_naive()
                reg.waiver_legal_name_signature = sig
                reg.waiver_legal_name_signature_sha256 = sha_cur
                reg.waiver_signature_submitted_at = now

    db.session.commit()
    return jsonify({"success": True})


@login_required
def get_my_team_registration_league(league_url):
    """Get current team's registration for this league."""
    from app.services.registration_resolver import team_registration_for_tournament

    if not is_team(current_user):
        return jsonify({"error": "Only teams have team registrations"}), 400

    league, err = require_league(league_url)
    if err:
        return jsonify({"error": "Not found" if err == 404 else "Forbidden"}), err

    class LeagueContext:
        def __init__(self, league):
            self.league_id = league.url
            self.url = None

    ctx = LeagueContext(league)
    reg = team_registration_for_tournament(ctx, current_user.id)

    if not reg:
        return jsonify({"error": "Not registered"}), 404

    return jsonify(
        {
            "registration": {
                "id": reg.id,
                "pseudonym": reg.pseudonym,
                "shortname": reg.shortname,
                "status": (reg.status.value if hasattr(reg.status, "value") else str(reg.status)),
            }
        }
    )


@login_required
def update_my_team_registration_league(league_url):
    """Update current team's registration for this league."""
    from app.services.registration_resolver import team_registration_for_tournament

    if not is_team(current_user):
        return jsonify({"error": "Only teams can edit their registration"}), 400

    league, err = require_league(league_url)
    if err:
        return jsonify({"error": "Not found" if err == 404 else "Forbidden"}), err

    if not league.registrable_config or not league.registrable_config.team_registration_open:
        return jsonify({"error": "Registration changes are locked"}), 403

    class LeagueContext:
        def __init__(self, league):
            self.league_id = league.url
            self.url = None

    ctx = LeagueContext(league)
    reg = team_registration_for_tournament(ctx, current_user.id)

    if not reg:
        return jsonify({"error": "Not registered"}), 404

    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400

    if "pseudonym" in data:
        pseudonym = data["pseudonym"].strip()
        pn_err = team_pseudonym_char_error(pseudonym)
        if pn_err:
            return jsonify({"error": pn_err}), 400
        if not pseudonym:
            return jsonify({"error": "Team name is required"}), 400
        reg.pseudonym = pseudonym

    if "shortname" in data:
        raw = data.get("shortname")
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            reg.shortname = None
        else:
            reg.shortname = raw.strip()

    db.session.commit()
    return jsonify({"success": True})


@login_required
def league_mark_team_paid(league_url):
    """Mark team payment status (league TO only)."""
    league, err = require_league(league_url)
    if err:
        return jsonify({"error": "Not found" if err == 404 else "Forbidden"}), err
    if not PermissionService.is_league_organizer(league_url, current_user):
        return (
            jsonify(
                {
                    "success": False,
                    "error": "Only league organizers can perform this action",
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

    reg = TeamRegistration.query.filter_by(id=reg_id, league_id=league_url).first_or_404()
    reg.paid = paid
    reg.amount_paid = amount_paid
    reg.payment_method = payment_method
    reg.payment_reference = payment_reference
    reg.payment_notes = payment_notes
    reg.paid_at = now_utc_naive() if paid else None
    db.session.commit()
    return jsonify({"success": True, "message": "Team payment updated"}), 200


@login_required
def league_mark_player_paid(league_url):
    """Mark player payment status (league TO only)."""
    league, err = require_league(league_url)
    if err:
        return jsonify({"error": "Not found" if err == 404 else "Forbidden"}), err
    if not PermissionService.is_league_organizer(league_url, current_user):
        return (
            jsonify(
                {
                    "success": False,
                    "error": "Only league organizers can perform this action",
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

    reg = PlayerRegistration.query.filter_by(id=reg_id, league_id=league_url).first_or_404()
    reg.paid = paid
    reg.amount_paid = amount_paid
    reg.payment_method = payment_method
    reg.payment_reference = payment_reference
    reg.payment_notes = payment_notes
    reg.paid_at = now_utc_naive() if paid else None
    db.session.commit()
    return jsonify({"success": True, "message": "Player payment updated"}), 200


@login_required
def league_deregister_any_team(league_url):
    """Deregister any team (league TO only)."""
    league, err = require_league(league_url)
    if err:
        return jsonify({"error": "Not found" if err == 404 else "Forbidden"}), err
    if not PermissionService.is_league_organizer(league_url, current_user):
        return (
            jsonify(
                {
                    "success": False,
                    "error": "Only league organizers can perform this action",
                }
            ),
            403,
        )

    team_id = request.form.get("team_id")
    if not team_id:
        return jsonify({"success": False, "error": "Team ID is required"}), 400

    team_registration = TeamRegistration.query.filter_by(
        league_id=league_url, team=team_id, status=RegistrationStatus.CONFIRMED
    ).first()

    if team_registration:
        team_registration.status = RegistrationStatus.CANCELLED
        PlayerRegistration.query.filter_by(league_id=league_url, team=team_id).update(
            {"status": RegistrationStatus.CANCELLED}
        )
        db.session.commit()
        return (
            jsonify({"success": True, "message": "Team successfully deregistered"}),
            200,
        )
    return (
        jsonify({"success": False, "error": "Team not found or already deregistered"}),
        404,
    )


@login_required
def league_deregister_any_player(league_url):
    """Deregister any player (league TO only)."""
    league, err = require_league(league_url)
    if err:
        return jsonify({"error": "Not found" if err == 404 else "Forbidden"}), err
    if not PermissionService.is_league_organizer(league_url, current_user):
        return (
            jsonify(
                {
                    "success": False,
                    "error": "Only league organizers can perform this action",
                }
            ),
            403,
        )

    player_id = request.form.get("player_id")
    if not player_id:
        return jsonify({"success": False, "error": "Player ID is required"}), 400

    player_registration = (
        PlayerRegistration.query.filter_by(league_id=league_url, player=player_id)
        .filter(PlayerRegistration.status.in_([RegistrationStatus.PENDING_TEAM_APPROVAL, RegistrationStatus.CONFIRMED]))
        .first()
    )

    if player_registration:
        player_registration.status = RegistrationStatus.CANCELLED
        db.session.commit()
        return (
            jsonify({"success": True, "message": "Player successfully deregistered"}),
            200,
        )
    return (
        jsonify({"success": False, "error": "Player not found or already deregistered"}),
        404,
    )


@login_required
def league_accept_invitation(league_url, invitation_id):
    """Accept a pending player registration (league roster)."""
    if not is_team(current_user):
        return (
            jsonify({"success": False, "error": "Only teams can accept invitations"}),
            403,
        )

    player_registration = PlayerRegistration.query.filter_by(
        id=invitation_id,
        league_id=league_url,
        team=current_user.id,
        status=RegistrationStatus.PENDING_TEAM_APPROVAL,
    ).first_or_404()

    player_registration.status = RegistrationStatus.CONFIRMED
    db.session.commit()
    return (
        jsonify({"success": True, "message": "Player approved! They are now on your team."}),
        200,
    )


@login_required
def league_decline_invitation(league_url, invitation_id):
    """Decline a pending player registration (league roster)."""
    if not is_team(current_user):
        return (
            jsonify({"success": False, "error": "Only teams can decline invitations"}),
            403,
        )

    player_registration = PlayerRegistration.query.filter_by(
        id=invitation_id,
        league_id=league_url,
        team=current_user.id,
        status=RegistrationStatus.PENDING_TEAM_APPROVAL,
    ).first_or_404()

    player_registration.status = RegistrationStatus.REJECTED
    db.session.commit()
    return jsonify({"success": True, "message": "Player request declined"}), 200


def _check_to(tournament_url):
    if not current_user.is_authenticated:
        return False
    return PermissionService.is_tournament_organizer(tournament_url, current_user)


@login_required
def get_my_player_registration(tournament_url):
    """Get current player's registration for this tournament."""
    if not is_player(current_user):
        return jsonify({"error": "Only players have player registrations"}), 400

    from app.services.registration_resolver import (
        player_registration_for_tournament,
        team_registration_for_tournament,
    )

    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()
    reg = player_registration_for_tournament(tournament, current_user.id)

    if not reg:
        return jsonify({"error": "Not registered"}), 404

    # Get current team info if any
    current_team = None
    if reg.team:
        team_reg = team_registration_for_tournament(tournament, reg.team)
        if team_reg:
            current_team = {
                "id": reg.team,
                "pseudonym": team_reg.pseudonym,
                "shortname": team_reg.shortname,
            }

    cfg = get_registrable_config(tournament)
    w = player_reg_waiver_api(reg, cfg)
    return jsonify(
        {
            "registration": {
                "id": reg.id,
                "jersey_name": reg.jersey_name,
                "jersey_number": reg.jersey_number,
                "team": reg.team,
                "status": (reg.status.value if hasattr(reg.status, "value") else str(reg.status)),
            },
            "current_team": current_team,
            "waiver_required": w["waiver_required"],
            "waiver_filepath": w["waiver_filepath"],
            "waiver_sha256": w["waiver_sha256"],
            "waiver_signature_valid": w["waiver_signature_valid"],
            "waiver_legal_name_signature": w["waiver_legal_name_signature"],
        }
    )


@login_required
def update_my_player_registration(tournament_url):
    """Update current player's registration."""
    from app.services.registration_resolver import player_registration_for_tournament

    if not is_player(current_user):
        return jsonify({"error": "Only players can edit their registration"}), 400

    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()
    cfg = get_registrable_config(tournament)
    reg_open = bool(cfg.player_registration_open) if cfg else False
    if not reg_open:
        return jsonify({"error": "Registration changes are locked"}), 403

    reg = player_registration_for_tournament(tournament, current_user.id)

    if not reg:
        return jsonify({"error": "Not registered"}), 404

    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400

    if "jersey_name" in data:
        reg.jersey_name = data["jersey_name"]
    if "jersey_number" in data:
        reg.jersey_number = data["jersey_number"]

    # Team change logic
    if "team" in data:
        new_team_id = data["team"] or None
        if reg.team != new_team_id:
            reg.team = new_team_id
            if new_team_id:
                reg.status = RegistrationStatus.PENDING_TEAM_APPROVAL
            else:
                reg.status = RegistrationStatus.CONFIRMED

    if "waiver_legal_name_signature" in data and data["waiver_legal_name_signature"]:
        cfg = get_registrable_config(tournament)
        sig = (data.get("waiver_legal_name_signature") or "").strip()
        if cfg and getattr(cfg, "waiver_filepath", None) and sig:
            sha_cur = getattr(cfg, "waiver_sha256", None)
            if sha_cur:
                now = now_utc_naive()
                reg.waiver_legal_name_signature = sig
                reg.waiver_legal_name_signature_sha256 = sha_cur
                reg.waiver_signature_submitted_at = now

    db.session.commit()
    return jsonify({"success": True})


@login_required
def get_my_team_registration(tournament_url):
    """Get current team's registration for this tournament."""
    from app.services.registration_resolver import team_registration_for_tournament

    if not is_team(current_user):
        return jsonify({"error": "Only teams have team registrations"}), 400

    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()
    reg = team_registration_for_tournament(tournament, current_user.id)

    if not reg:
        return jsonify({"error": "Not registered"}), 404

    return jsonify(
        {
            "registration": {
                "id": reg.id,
                "pseudonym": reg.pseudonym,
                "shortname": reg.shortname,
                "status": (reg.status.value if hasattr(reg.status, "value") else str(reg.status)),
            }
        }
    )


@login_required
def update_my_team_registration(tournament_url):
    """Update current team's registration."""
    from app.services.registration_resolver import team_registration_for_tournament

    if not is_team(current_user):
        return jsonify({"error": "Only teams can edit their registration"}), 400

    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()
    cfg = get_registrable_config(tournament)
    reg_open = bool(cfg.team_registration_open) if cfg else False
    if not reg_open:
        return jsonify({"error": "Registration changes are locked"}), 403

    reg = team_registration_for_tournament(tournament, current_user.id)

    if not reg:
        return jsonify({"error": "Not registered"}), 404

    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400

    if "pseudonym" in data:
        pseudonym = data["pseudonym"].strip()
        pn_err = team_pseudonym_char_error(pseudonym)
        if pn_err:
            return jsonify({"error": pn_err}), 400
        if not pseudonym:
            return jsonify({"error": "Team name is required"}), 400
        reg.pseudonym = pseudonym

    if "shortname" in data:
        raw = data.get("shortname")
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            reg.shortname = None
        else:
            reg.shortname = raw.strip()

    db.session.commit()
    return jsonify({"success": True})

