"""Internal JSON API for the Dioxus SPA.

Hosts the ``_api`` blueprint - the catch-all for endpoints that don't
have a more specific home (tournament listing, match detail, points
CRUD, schedule queries, rosters, head-ref permissions, photos, profile
updates, search, ...).
"""

from flask import Blueprint, g, request, jsonify, current_app
from datetime import datetime, timezone
import collections
import os
from flask_login import current_user, login_required
from sqlalchemy import func
from sqlalchemy.orm.attributes import flag_modified
from app.services._common import current_user_type, Scope
from app.services.permission_service import PermissionService
from app.services.tournament_service import TournamentService
from app.utils.decorators import require_json_body
from app.utils.helpers import (
    check_tournament_access,
    can_head_ref_match,
    resolve_team_name_to_id,
    resolve_tag_to_team,
    get_registrable_config,
)
from app.utils.match_ref_resolution import (
    refs_string_to_tokens,
    resolve_refs_slots,
    resolve_team_slot,
)
from app.utils.dependencies import apply_match_dependencies
from app.services.dual_write import (
    clear_match_referees,
    get_camera_timepoint_arrays,
    get_head_ref_allowlist_ids,
    get_match_player_ids,
    get_match_ref_initials,
    get_match_ref_team_ids,
    get_match_referee_rows,
    get_match_refs_csv,
    get_match_refs_initial_csv,
    set_match_referees_from_csv,
)
from app.serializers.league_serializer import require_league
from app.serializers.match_note_serializer import MatchNoteSerializer
from app.serializers.registration_serializer import player_reg_waiver_api, serialize_manage
from app.routes.tournaments import update_match_previous_link
from app.utils.scheduling import (
    recompute_all_match_times,
    compute_dynamic_match_nominal_start_time,
    validate_match_input,
)
from app.utils.name_validation import match_name_char_error, team_pseudonym_char_error
from app.utils.datetime_helpers import to_iso_z, now_utc_naive
from app.utils.recording_retry import current_user_can_retry_finalization
from app.utils.user_helpers import is_player, is_team
from app.domain.enums import (
    RegistrationStatus,
    MatchStatus,
    ScheduleType,
    SetType,
    WinnerSide,
)
from models import (
    Player,
    Team,
    Tournament,
    League,
    Match,
    Point,
    Field,
    Camera,
    Tag,
    Injury,
    MatchNote,
    TeamRegistration,
    PlayerRegistration,
    db,
)
import json

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


def _tournament_to_dict(t) -> dict:
    """Serialise a :class:`~app.models.tournament.Tournament` to an API dict.

    Includes registration status, fee, waiver, head-ref policy, and league
    membership information.  Falls back gracefully when the tournament's
    :class:`~app.models.registrable_config.RegistrableConfig` is not found.

    Args:
        t: The tournament ORM instance to serialise.

    Returns:
        A JSON-serialisable dictionary suitable for the SPA.
    """
    cfg = get_registrable_config(t)
    end = t.end_date.isoformat() if t.end_date else None
    start = t.start_date.isoformat() if t.start_date else None
    team_reg_open = bool(cfg.team_registration_open) if cfg else False
    player_reg_open = bool(cfg.player_registration_open) if cfg else False

    out = {
        "url": t.url,
        "name": t.name,
        "start_date": start,
        "end_date": end,
        "location": t.location,
        "published": t.published,
        "n_max_teams": getattr(cfg, "n_max_teams", None) if cfg else None,
        "schedule_published": getattr(t, "schedule_published", False),
        # Legacy aggregate flag kept for compatibility: true if either team or player registration open.
        "registration_open": bool(team_reg_open or player_reg_open),
        "team_registration_open": bool(team_reg_open),
        "player_registration_open": bool(player_reg_open),
        "bracket": bool(getattr(t, "bracket", None)),
        "about": getattr(t, "about", None),
        "team_reg_fee": cfg.team_reg_fee if cfg else None,
        "player_reg_fee": cfg.player_reg_fee if cfg else None,
        "max_team_size_roster": (getattr(cfg, "max_team_size_roster", None) if cfg else None),
        "max_team_size_field": (getattr(cfg, "max_team_size_field", None) if cfg else None),
        "terms_link": cfg.terms_link if cfg else None,
        "head_refs_allowed_list": ",".join(get_head_ref_allowlist_ids(t)) or None,
        "head_refs_allow_reffing_teams": bool(getattr(t, "head_refs_allow_reffing_teams", False)),
        "head_refs_allow_anyone": bool(getattr(t, "head_refs_allow_anyone", False)),
    }
    if cfg:
        wf = getattr(cfg, "waiver_filepath", None)
        out["waiver_required"] = bool(wf)
        out["waiver_filepath"] = wf
        out["waiver_sha256"] = getattr(cfg, "waiver_sha256", None)
    else:
        out["waiver_required"] = False
        out["waiver_filepath"] = None
        out["waiver_sha256"] = None
    if getattr(t, "league_id", None):
        league = League.query.get(t.league_id)
        if league and league.registrable_config:
            rc = league.registrable_config
            l_team_open = bool(rc.team_registration_open)
            l_player_open = bool(rc.player_registration_open)
            out["league"] = {
                "league_url": league.url,
                "name": league.name,
                "registration_open": l_team_open or l_player_open,
                "team_registration_open": l_team_open,
                "player_registration_open": l_player_open,
                "team_reg_fee": rc.team_reg_fee,
                "player_reg_fee": rc.player_reg_fee,
            }
        elif league:
            out["league"] = {"league_url": league.url, "name": league.name}
        else:
            out["league"] = None
    else:
        out["league"] = None
    return out


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


@bp.route("/tournaments", methods=["GET"])
def tournaments():
    """List tournaments (same visibility as homepage). Returns { tournaments, team_counts, user_reg_status }."""
    ctx = TournamentService.get_homepage_context(current_user)
    team_counts = ctx["team_counts"]
    user_reg_status = ctx["user_reg_status"]
    all_tournaments = [_tournament_to_dict(t) for t in ctx["tournaments"]]
    return jsonify(
        {
            "tournaments": all_tournaments,
            "team_counts": team_counts,
            "user_reg_status": user_reg_status,
        }
    )


def _require_tournament(tournament_url):
    has_access, tournament = check_tournament_access(tournament_url)
    if not has_access or not tournament:
        return None, 404
    return tournament, None


@bp.route("/tournaments/<tournament_url>", methods=["GET"])
def tournament_detail(tournament_url):
    """Tournament detail: teams with counts, unattached players, to_entries, is_current_*_registered."""
    from app.services.registration_resolver import (
        team_registrations_for_tournament,
        player_registrations_for_tournament,
        is_team_registered,
        is_player_registered,
        to_entries_for_tournament,
    )

    tournament, err = _require_tournament(tournament_url)
    if err:
        return jsonify({"error": "Not found"}), err
    team_regs = team_registrations_for_tournament(tournament)
    team_ids = [tr.team for tr in team_regs]
    teams_by_id = {t.id: t for t in Team.query.filter(Team.id.in_(team_ids)).all()} if team_ids else {}
    all_prs = player_registrations_for_tournament(tournament, statuses=[RegistrationStatus.CONFIRMED])
    counts_by_team = collections.Counter(pr.team for pr in all_prs if pr.team)
    teams_with_counts = []
    for team_reg in team_regs:
        team = teams_by_id.get(team_reg.team)
        teams_with_counts.append(
            {
                "team_id": team_reg.team,
                "team_name": team.name if team else team_reg.team,
                "pseudonym": team_reg.pseudonym,
                "shortname": team_reg.shortname,
                "player_count": counts_by_team.get(team_reg.team, 0),
                "registered_at": _dt_iso(getattr(team_reg, "registered_at", None)),
                "profile_photo": team.profile_photo if team else None,
            }
        )
    unattached_prs = list(
        player_registrations_for_tournament(
            tournament,
            unattached_only=True,
            statuses=[RegistrationStatus.CONFIRMED],
        )
    )
    unattached_player_ids = [pr.player for pr in unattached_prs]
    unattached_players_by_id = (
        {p.id: p for p in Player.query.filter(Player.id.in_(unattached_player_ids)).all()}
        if unattached_player_ids
        else {}
    )
    unattached = []
    for pr in unattached_prs:
        p = unattached_players_by_id.get(pr.player)
        unattached.append(
            {
                "player_id": pr.player,
                "player_name": p.name if p else pr.player,
                "jersey_number": getattr(pr, "jersey_number", None),
                "jersey_name": getattr(pr, "jersey_name", None),
                "registered_at": _dt_iso(getattr(pr, "registered_at", None)),
                "profile_photo": getattr(p, "profile_photo", None) if p else None,
            }
        )
    to_rows = to_entries_for_tournament(tournament)
    to_player_ids = [e.user_id for e in to_rows if e.user_type == "player"]
    to_team_ids = [e.user_id for e in to_rows if e.user_type == "team"]
    to_players_by_id = (
        {p.id: p for p in Player.query.filter(Player.id.in_(to_player_ids)).all()} if to_player_ids else {}
    )
    to_teams_by_id = {t.id: t for t in Team.query.filter(Team.id.in_(to_team_ids)).all()} if to_team_ids else {}
    to_entries = []
    for e in to_rows:
        if e.user_type == "player":
            user = to_players_by_id.get(e.user_id)
        else:
            user = to_teams_by_id.get(e.user_id)
        user_name = user.name if user else e.user_id
        is_current = (
            current_user.is_authenticated and current_user.id == e.user_id and current_user_type() == e.user_type
        )
        to_entries.append(
            {
                "id": e.id,
                "user_id": e.user_id,
                "user_type": e.user_type,
                "user_name": user_name,
                "is_current_user": is_current,
            }
        )
    is_current_team_registered = False
    is_current_player_registered = False
    if current_user.is_authenticated:
        if is_team(current_user):
            is_current_team_registered = is_team_registered(tournament, current_user.id)
        else:
            is_current_player_registered = is_player_registered(tournament, current_user.id)

    from app.utils.helpers import get_penalty_types_for_tournament

    penalty_types = get_penalty_types_for_tournament(tournament)
    penalty_types_data = [{"id": t.id, "name": t.name, "color": t.color, "desc": (t.desc or "")} for t in penalty_types]

    return jsonify(
        {
            "tournament": _tournament_to_dict(tournament),
            "teams_with_counts": teams_with_counts,
            "unattached_players": unattached,
            "to_entries": to_entries,
            "is_current_team_registered": is_current_team_registered,
            "is_current_player_registered": is_current_player_registered,
            "penalty_types": penalty_types_data,
            "manual_footage_uploads_enabled": bool(current_app.config.get("ENABLE_MANUAL_FOOTAGE_UPLOADS", False)),
        }
    )


@bp.route("/tournaments/<tournament_url>/manage", methods=["GET"])
@login_required
def tournament_manage_api(tournament_url):
    """Tournament registration management (TO only)."""
    if not _check_to(tournament_url):
        return jsonify({"error": "Forbidden"}), 403

    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()
    if tournament.league_id:
        return (
            jsonify(
                {
                    "error": "Registration management for league events is on the league page.",
                }
            ),
            403,
        )

    search_query = (request.args.get("search") or "").strip()
    search_type = (request.args.get("type") or "both").lower()
    cfg = get_registrable_config(tournament)
    return jsonify(serialize_manage(Scope.event(tournament_url), search_query, search_type, cfg))


@bp.route("/tournaments/<tournament_url>/invitations", methods=["GET"])
@login_required
def tournament_invitations_api(tournament_url):
    if not is_team(current_user):
        return jsonify({"error": "Only teams can view invitations"}), 403

    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()
    team_registration = TeamRegistration.query.filter_by(
        event=tournament_url, team=current_user.id, status=RegistrationStatus.CONFIRMED
    ).first()
    if not team_registration:
        return jsonify({"error": "Not registered"}), 404

    pending_regs = PlayerRegistration.query.filter_by(
        event=tournament_url,
        team=current_user.id,
        status=RegistrationStatus.PENDING_TEAM_APPROVAL,
    ).all()
    pending_with_players = []
    for reg in pending_regs:
        player = Player.query.get(reg.player)
        if player:
            pending_with_players.append({"registration": reg, "player": player})

    current_team_size = PlayerRegistration.query.filter_by(
        event=tournament_url, team=current_user.id, status=RegistrationStatus.CONFIRMED
    ).count()

    all_player_registrations = PlayerRegistration.query.filter_by(event=tournament_url, team=current_user.id).all()
    team_roster = []
    for reg in all_player_registrations:
        player = Player.query.get(reg.player)
        if player:
            team_roster.append({"player": player, "registration": reg})

    return jsonify(
        {
            "tournament": _tournament_to_dict(tournament),
            "team_registration": {
                "id": team_registration.id,
                "pseudonym": team_registration.pseudonym,
                "shortname": team_registration.shortname,
            },
            "current_team_size": current_team_size,
            "invitations": [
                {
                    "registration": {
                        "id": inv["registration"].id,
                        "jersey_name": inv["registration"].jersey_name,
                        "jersey_number": inv["registration"].jersey_number,
                    },
                    "player": {
                        "id": inv["player"].id,
                        "name": inv["player"].name,
                        "profile_photo": inv["player"].profile_photo,
                    },
                }
                for inv in pending_with_players
            ],
            "team_roster": [
                {
                    "registration": {
                        "id": r["registration"].id,
                        "jersey_name": r["registration"].jersey_name,
                        "jersey_number": r["registration"].jersey_number,
                        "status": (
                            r["registration"].status.value
                            if hasattr(r["registration"].status, "value")
                            else str(r["registration"].status)
                        ),
                        "paid": bool(r["registration"].paid),
                        "amount_paid": r["registration"].amount_paid or 0.0,
                    },
                    "player": {
                        "id": r["player"].id,
                        "name": r["player"].name,
                        "profile_photo": r["player"].profile_photo,
                    },
                }
                for r in team_roster
            ],
        }
    )


@bp.route("/tournaments/<tournament_url>/bracket-setup-data", methods=["GET"])
@login_required
def tournament_bracket_setup_data_api(tournament_url):
    """Raw bracket configuration for the SPA bracket-setup page.

    This returns the underlying TOML data (already parsed) so that the
    Dioxus frontend can render and edit bracket annotations while the
    existing HTML form endpoint continues to handle multipart uploads.
    """
    # Only TOs may access bracket setup data
    if not _check_to(tournament_url):
        return jsonify({"error": "Forbidden"}), 403

    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()

    brackets_data = []
    if tournament.bracket:
        try:
            import tomli

            parsed = tomli.loads(tournament.bracket)
            brackets_data = parsed.get("brackets", [])
        except Exception:
            # If parsing fails, just return an empty brackets list so the UI
            # can present a clean state rather than a hard error.
            brackets_data = []

    return jsonify(
        {
            "tournament": _tournament_to_dict(tournament),
            "brackets": brackets_data,
        }
    )


@bp.route("/tournaments/<tournament_url>/bracket-setup", methods=["POST"])
@login_required
@require_json_body()
def tournament_bracket_setup_save_api(tournament_url):
    """Save bracket configuration from the SPA."""
    if not _check_to(tournament_url):
        return jsonify({"error": "Forbidden"}), 403

    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()

    data = g.json_body
    brackets = data.get("brackets", [])

    def escape_toml_string(s):
        """Escape special characters in TOML strings."""
        s = str(s)
        s = s.replace("\\", "\\\\")
        s = s.replace('"', '\\"')
        s = s.replace("\n", "\\n")
        s = s.replace("\t", "\\t")
        return s

    toml_lines = []
    for bracket in brackets:
        name = (bracket.get("name") or "").strip()
        image = (bracket.get("image") or "").strip()
        if not name or not image:
            continue

        toml_lines.append("[[brackets]]")
        toml_lines.append(f'name = "{escape_toml_string(name)}"')
        toml_lines.append(f'image = "{escape_toml_string(image)}"')
        toml_lines.append("")

        teams = bracket.get("teams") or []
        for team in teams:
            team_ref = (team.get("team") or "").strip()
            if not team_ref:
                continue
            try:
                x = int(team.get("x", 0) or 0)
                y = int(team.get("y", 0) or 0)
                halign = (team.get("halign") or "center").strip() or "center"
                valign = (team.get("valign") or "center").strip() or "center"
                size = int(team.get("size", 20) or 20)
            except (ValueError, TypeError):
                continue

            toml_lines.append("[[brackets.teams]]")
            toml_lines.append(f'team = "{escape_toml_string(team_ref)}"')
            toml_lines.append(f"x = {x}")
            toml_lines.append(f"y = {y}")
            toml_lines.append(f'halign = "{escape_toml_string(halign)}"')
            toml_lines.append(f'valign = "{escape_toml_string(valign)}"')
            toml_lines.append(f"size = {size}")
            toml_lines.append("")

    tournament.bracket = "\n".join(toml_lines)
    db.session.commit()

    return jsonify({"success": True})


@bp.route("/tournaments/<tournament_url>/bracket-upload-bytes", methods=["POST"])
@login_required
def tournament_bracket_upload_bytes_api(tournament_url):
    """Upload a single bracket image from the SPA using raw bytes.

    The client sends the file contents as the request body and passes
    `filename` and `bracket_index` as query parameters.
    """
    if not _check_to(tournament_url):
        return jsonify({"error": "Forbidden"}), 403

    Tournament.query.filter_by(url=tournament_url).first_or_404()
    db.session.remove()

    from flask import current_app
    from datetime import datetime, timezone

    original_name = request.args.get("filename", "bracket.png")
    bracket_index = request.args.get("bracket_index", "0")

    # Derive a safe extension from the original filename
    _, ext = os.path.splitext(original_name)
    if not ext:
        ext = ".png"

    # Normalize bracket index to digits only
    safe_index = "".join(ch for ch in bracket_index if ch.isdigit()) or "0"

    upload_dir = os.path.join(current_app.root_path, "../static", "uploads", "brackets")
    os.makedirs(upload_dir, exist_ok=True)

    filename = f"bracket_{tournament_url}_{safe_index}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}{ext}"
    file_path = os.path.join(upload_dir, filename)

    try:
        data = request.get_data() or b""
        with open(file_path, "wb") as f:
            f.write(data)
    except Exception as e:
        return jsonify({"error": f"Error saving image: {e}"}), 500

    rel_path = f"uploads/brackets/{filename}"
    return jsonify({"success": True, "path": rel_path})


@bp.route("/tournaments/<tournament_url>/bracket", methods=["GET"])
def tournament_bracket_api(tournament_url):
    has_access, tournament = check_tournament_access(tournament_url)
    if not has_access or not tournament:
        return jsonify({"error": "Not found"}), 404

    is_to = False
    if current_user.is_authenticated:
        is_to = PermissionService.is_tournament_organizer(tournament_url, current_user)

    if not tournament.bracket:
        return jsonify({"error": "Bracket is not available"}), 404
    if not tournament.schedule_published and not is_to:
        return jsonify({"error": "Bracket is not available"}), 403

    try:
        import tomli

        bracket_data = tomli.loads(tournament.bracket)
    except Exception:
        return jsonify({"error": "Error parsing bracket data"}), 400

    processed_brackets = []
    brackets = bracket_data.get("brackets", [])
    for bracket in brackets:
        bracket_name = bracket.get("name", "")
        bracket_image = bracket.get("image", "")
        teams = bracket.get("teams", [])
        processed_teams = []
        for team_entry in teams:
            team_ref = team_entry.get("team", "")
            x = team_entry.get("x", 0)
            y = team_entry.get("y", 0)
            halign = team_entry.get("halign", "center")
            valign = team_entry.get("valign", "center")
            size = team_entry.get("size", 20)

            team_info = None
            is_reference = False
            is_tag = False
            match_name = None

            if team_ref.lower().startswith("tag::"):
                tag_name = team_ref[5:].strip()
                if tag_name:
                    tag = Tag.query.filter_by(event=tournament_url, name=tag_name).first()
                    if tag and tag.team:
                        team_reg = TeamRegistration.query.filter_by(
                            event=tournament_url,
                            team=tag.team,
                            status=RegistrationStatus.CONFIRMED,
                        ).first()
                        if team_reg:
                            team = Team.query.get(tag.team)
                            team_info = {
                                "id": tag.team,
                                "pseudonym": team_reg.pseudonym,
                                "shortname": team_reg.shortname,
                                "profile_photo": team.profile_photo if team else None,
                                "display_text": team_reg.pseudonym,
                            }
                        else:
                            team_info = {"display_text": f"tag::{tag_name}"}
                            is_tag = True
                    elif tag:
                        team_info = {"display_text": f"tag::{tag_name}"}
                        is_tag = True
            elif "::" in team_ref:
                parts = team_ref.split("::", 1)
                match_name = parts[0].strip()
                ref_type = parts[1].strip() if len(parts) > 1 else ""
                match = Match.query.filter_by(event=tournament_url, name=match_name).first()
                if match and match.status == MatchStatus.COMPLETED and match.match_winner:
                    if ref_type == "winner":
                        team_id = match.team1 if match.match_winner == "TEAM1" else match.team2
                    elif ref_type == "loser":
                        team_id = match.team2 if match.match_winner == "TEAM1" else match.team1
                    else:
                        team_id = None
                    if team_id:
                        team_reg = TeamRegistration.query.filter_by(
                            event=tournament_url,
                            team=team_id,
                            status=RegistrationStatus.CONFIRMED,
                        ).first()
                        if team_reg:
                            team = Team.query.get(team_id)
                            team_info = {
                                "id": team_id,
                                "pseudonym": team_reg.pseudonym,
                                "shortname": team_reg.shortname,
                                "profile_photo": team.profile_photo if team else None,
                                "display_text": team_reg.pseudonym,
                            }
                            is_reference = True
                elif match:
                    team_info = {"display_text": team_ref.replace("::", " ")}
                    is_reference = True
                else:
                    team_info = {"display_text": team_ref.replace("::", " ")}
                    is_reference = True
            elif team_ref:
                team_reg = TeamRegistration.query.filter_by(
                    event=tournament_url,
                    team=team_ref,
                    status=RegistrationStatus.CONFIRMED,
                ).first()
                if team_reg:
                    team = Team.query.get(team_ref)
                    team_info = {
                        "id": team_ref,
                        "pseudonym": team_reg.pseudonym,
                        "shortname": team_reg.shortname,
                        "profile_photo": team.profile_photo if team else None,
                        "display_text": team_reg.pseudonym,
                    }
                else:
                    tag = Tag.query.filter_by(event=tournament_url, name=team_ref).first()
                    if tag and tag.team:
                        team_reg = TeamRegistration.query.filter_by(
                            event=tournament_url,
                            team=tag.team,
                            status=RegistrationStatus.CONFIRMED,
                        ).first()
                        if team_reg:
                            team = Team.query.get(tag.team)
                            team_info = {
                                "id": tag.team,
                                "pseudonym": team_reg.pseudonym,
                                "shortname": team_reg.shortname,
                                "profile_photo": team.profile_photo if team else None,
                                "display_text": team_reg.pseudonym,
                            }
                        else:
                            team_info = {"display_text": f"tag::{tag.name}"}
                            is_tag = True
                    elif tag:
                        team_info = {"display_text": f"tag::{tag.name}"}
                        is_tag = True

            processed_teams.append(
                {
                    "team_info": team_info,
                    "x": x,
                    "y": y,
                    "halign": halign,
                    "valign": valign,
                    "size": size,
                    "is_reference": is_reference,
                    "is_tag": is_tag,
                    "match_name": match_name if is_reference else None,
                }
            )

        processed_brackets.append({"name": bracket_name, "image": bracket_image, "teams": processed_teams})

    return jsonify({"tournament": _tournament_to_dict(tournament), "brackets": processed_brackets})


@bp.route("/tournaments/<tournament_url>/start-match", methods=["GET"])
@login_required
def start_match_data_api(tournament_url):
    match_id = request.args.get("match_id")
    if not match_id:
        return jsonify({"error": "Match ID required"}), 400

    match = Match.query.get(match_id)
    if not match or match.event != tournament_url:
        return jsonify({"error": "Match not found"}), 404

    from app.services.match_start_eligibility import get_can_start_and_reasons

    can_start, block_reasons, _ = get_can_start_and_reasons(tournament_url, match, current_user)
    if not can_start:
        error_msg = block_reasons[0] if block_reasons else "Cannot start this match."
        return jsonify({"error": error_msg, "reasons": block_reasons}), 400

    tournament = Tournament.query.get(tournament_url)
    from app.services.registration_resolver import player_registrations_for_tournament

    all_prs = player_registrations_for_tournament(tournament, statuses=[RegistrationStatus.CONFIRMED])
    team1_prs = [pr for pr in all_prs if pr.team == match.team1]
    team2_prs = [pr for pr in all_prs if pr.team == match.team2]
    all_prs_list = all_prs

    team1_players = [(pr, Player.query.get(pr.player)) for pr in team1_prs]
    team2_players = [(pr, Player.query.get(pr.player)) for pr in team2_prs]
    all_players = [(pr, Player.query.get(pr.player)) for pr in all_prs_list]
    team1_players = [(pr, p) for pr, p in team1_players if p]
    team2_players = [(pr, p) for pr, p in team2_players if p]
    all_players = [(pr, p) for pr, p in all_players if p]

    injuries_map = {}
    try:
        all_player_ids = set(
            [pr.player for pr, _ in all_players]
            + [pr.player for pr, _ in team1_players]
            + [pr.player for pr, _ in team2_players]
        )
        if all_player_ids:
            active_injuries = Injury.query.filter(
                Injury.player.in_(list(all_player_ids)), Injury.active.is_(True)
            ).all()
            for inj in active_injuries:
                injuries_map.setdefault(inj.player, []).append(inj.message)
    except Exception:
        injuries_map = {}

    def _player_item(pr, player):
        return {
            "id": player.id,
            "name": player.name,
            "jersey_name": pr.jersey_name,
            "jersey_number": pr.jersey_number,
            "team": pr.team,
            "paid": bool(pr.paid),
            "injuries": injuries_map.get(player.id, []),
        }

    return jsonify(
        {
            "tournament": _tournament_to_dict(tournament),
            "match_info": {
                "uuid": match.uuid,
                "name": match.name,
                "field": match.field,
                "set_type": match.set_type.value if match.set_type else None,
                "refs": get_match_refs_csv(match) or None,
                "team1_name": _team_name_for_match(tournament, match, "team1"),
                "team2_name": _team_name_for_match(tournament, match, "team2"),
            },
            "team1_players": [_player_item(pr, p) for pr, p in team1_players],
            "team2_players": [_player_item(pr, p) for pr, p in team2_players],
            "all_players": [_player_item(pr, p) for pr, p in all_players],
        }
    )


@bp.route("/tournaments/<tournament_url>/start-match", methods=["POST"])
@login_required
def start_match_post_api(tournament_url):
    data = request.get_json() or {}
    match_id = data.get("match_id")
    if not match_id:
        return jsonify({"error": "Match ID required"}), 400

    from app.services.match_service import MatchService
    from app.utils.result_helpers import json_from_result

    team1_players = ",".join(data.get("team1_players") or [])
    team2_players = ",".join(data.get("team2_players") or [])
    match_notes = data.get("match_notes") or ""
    stones_per_set = data.get("stones_per_set")

    res = MatchService.start_match(
        tournament_url,
        match_id,
        current_user,
        team1_players_csv=team1_players,
        team2_players_csv=team2_players,
        match_notes=match_notes,
        stones_per_set=stones_per_set,
    )
    return json_from_result(
        res,
        ok_to_payload=lambda v: {"match_id": v.uuid},
        err_status_code=400,
    )


@bp.route("/tournaments/<tournament_url>/finalize-match", methods=["GET"])
@login_required
def finalize_match_data_api(tournament_url):
    match_id = request.args.get("match_id")
    if not match_id:
        return jsonify({"error": "Match ID required"}), 400

    match = Match.query.get(match_id)
    if not match or match.event != tournament_url:
        return jsonify({"error": "Match not found"}), 404

    if not can_head_ref_match(tournament_url, current_user.id, match=match):
        return jsonify({"error": "Forbidden"}), 403

    tournament = Tournament.query.get(tournament_url)
    points = Point.query.filter_by(match=match.uuid).order_by(Point.stamp).all()

    from models import MatchNote

    point_notes_map = {}
    stones_elapsed_map = {}

    def compute_stones_elapsed(start_dt, end_dt):
        try:
            if not start_dt or not end_dt:
                return 0
            start_epoch = start_dt.timestamp()
            end_epoch = end_dt.timestamp()
            start_count = int(start_epoch // 1.5)
            end_count = int(end_epoch // 1.5)
            val = end_count - start_count
            return val if val >= 0 else 0
        except Exception:
            return 0

    if points:
        point_ids = [p.uuid for p in points if getattr(p, "uuid", None)]
        for p in points:
            stones_elapsed_map[p.uuid] = compute_stones_elapsed(
                getattr(p, "stamp", None), getattr(p, "end_stamp", None)
            )
        if point_ids:
            notes = (
                MatchNote.query.filter_by(match=match.uuid)
                .filter(MatchNote.point_id.in_(point_ids))
                .order_by(MatchNote.created_at.asc())
                .all()
            )
            for n in notes:
                payload = MatchNoteSerializer.to_dict(n, tournament_url, match=match)
                point_notes_map.setdefault(n.point_id, []).append(
                    {
                        "text": payload.get("text"),
                        "target": payload.get("target"),
                        "player_id": payload.get("player_id"),
                        "player_name": payload.get("player_name"),
                        "player_display": payload.get("player_display"),
                        "team_id": payload.get("team_id"),
                        "created_at": payload.get("created_at"),
                    }
                )

    team1_score = sum(1 for p in points if p.winner == "TEAM1" and not p.rerolled)
    team2_score = sum(1 for p in points if p.winner == "TEAM2" and not p.rerolled)

    return jsonify(
        {
            "tournament": _tournament_to_dict(tournament),
            "match_info": {
                "uuid": match.uuid,
                "name": match.name,
                "team1_name": _team_name_for_match(tournament, match, "team1"),
                "team2_name": _team_name_for_match(tournament, match, "team2"),
            },
            "points": [
                {
                    "uuid": p.uuid,
                    "set_number": p.set_number,
                    "winner": p.winner,
                    "rerolled": p.rerolled,
                }
                for p in points
            ],
            "point_notes_map": point_notes_map,
            "stones_elapsed_map": stones_elapsed_map,
            "team1_score": team1_score,
            "team2_score": team2_score,
        }
    )


@bp.route("/tournaments/<tournament_url>/finalize-match", methods=["POST"])
@login_required
def finalize_match_post_api(tournament_url):
    data = request.get_json() or {}
    match_id = data.get("match_id")
    if not match_id:
        return jsonify({"error": "Match ID required"}), 400

    match = Match.query.get(match_id)
    if not match or match.event != tournament_url:
        return jsonify({"error": "Match not found"}), 404

    if not can_head_ref_match(tournament_url, current_user.id, match=match):
        return jsonify({"error": "Forbidden"}), 403

    match.status = MatchStatus.COMPLETED
    match_winner = data.get("match_winner")
    if not match_winner:
        return jsonify({"error": "Match winner required"}), 400

    match.completed_time = now_utc_naive()
    match.finalized_by = current_user.id
    match.final_notes = data.get("final_notes") or ""
    match.match_winner = match_winner
    match.finalized_at = now_utc_naive()

    if match.field:
        field_obj = Field.query.filter_by(event=tournament_url, name=match.field).first()
        if field_obj and field_obj.camera:
            from app.utils.camera_helpers import get_all_camera_stream_starts

            stream_starts = get_all_camera_stream_starts(field_obj)
            if stream_starts:
                existing_starts = {}
                if match.camera_stream_starts:
                    try:
                        existing_starts = json.loads(match.camera_stream_starts)
                    except json.JSONDecodeError:
                        pass
                existing_starts.update(stream_starts)
                match.camera_stream_starts = json.dumps(existing_starts)

    team1_signature = data.get("team1_signature")
    team2_signature = data.get("team2_signature")
    if team1_signature:
        match.team1_signature = team1_signature
    if team2_signature:
        match.team2_signature = team2_signature
    db.session.commit()

    try:
        apply_match_dependencies(tournament_url, match)
    except Exception as e:
        print(f"Dependency update error for match {match.name}: {e}")

    try:
        from app.utils.scheduling import recompute_all_match_times

        recompute_all_match_times(tournament_url)
        db.session.commit()
    except Exception as e:
        print(f"Error recomputing match times: {e}")

    return jsonify({"ok": True})


def _schedule_published_check(tournament_url, tournament):
    if tournament.schedule_published:
        return True
    if not current_user.is_authenticated:
        return False
    if PermissionService.is_tournament_organizer(tournament_url, current_user):
        return True
    if is_player(current_user) and can_head_ref_match(tournament_url, current_user.id, match=None):
        return True
    return False


@bp.route("/tournaments/<tournament_url>/schedule", methods=["GET"])
def tournament_schedule(tournament_url):
    """Schedule: matches, fields, team_options. Requires schedule_published or TO/head_ref."""
    tournament, err = _require_tournament(tournament_url)
    if err:
        return jsonify({"error": "Not found"}), err
    if not _schedule_published_check(tournament_url, tournament):
        return jsonify({"error": "Schedule not published"}), 403
    matches = Match.query.filter_by(event=tournament_url).order_by(Match.nominal_start_time).all()
    fields = [
        {"id": f.id, "name": f.name} for f in Field.query.filter_by(event=tournament_url).order_by(Field.name).all()
    ]
    team_options = []
    seen = set()
    from app.services.registration_resolver import team_registrations_for_tournament

    for tr in team_registrations_for_tournament(tournament):
        if tr.team not in seen:
            team = Team.query.get(tr.team)
            team_options.append(
                {
                    "id": tr.team,
                    "pseudonym": tr.pseudonym,
                    "shortname": tr.shortname,
                    "profile_photo": team.profile_photo if team else None,
                }
            )
            seen.add(tr.team)
    for m in matches:
        for initial, key in [(m.team1_initial, "team1"), (m.team2_initial, "team2")]:
            if not initial or initial in seen:
                continue
            if "::winner" in initial or "::loser" in initial or " winner" in initial or " loser" in initial:
                continue
            team_options.append({"id": initial, "pseudonym": initial, "shortname": None, "profile_photo": None})
            seen.add(initial)
    match_list = []
    for m in matches:
        match_list.append(
            {
                "uuid": m.uuid,
                "name": m.name,
                "field": m.field,
                "team1": m.team1,
                "team2": m.team2,
                "team1_initial": m.team1_initial,
                "team2_initial": m.team2_initial,
                "status": (m.status.value if hasattr(m.status, "value") else str(m.status)),
                "nominal_start_time": _dt_iso(m.nominal_start_time),
                "confirmed_start_time": _dt_iso(m.confirmed_start_time),
                "completed_time": _dt_iso(m.completed_time),
                "schedule_type": m.schedule_type.value if m.schedule_type else None,
                "set_type": m.set_type.value if m.set_type else None,
            }
        )
    return jsonify(
        {
            "tournament": _tournament_to_dict(tournament),
            "matches": match_list,
            "fields": fields,
            "team_options": team_options,
        }
    )


def _team_pseudonym_and_photo(tournament, team_id):
    """Return (pseudonym, profile_photo, shortname) for a team in a tournament context.

    Returns ``(None, None, None)`` if ``team_id`` is falsy.
    ``shortname`` is ``None`` if the team has no registration or no shortname.
    """
    from app.services.registration_resolver import team_registration_for_tournament

    if not team_id:
        return None, None, None
    reg = team_registration_for_tournament(tournament, team_id)
    pseudonym = reg.pseudonym if reg and reg.pseudonym else None
    team = Team.query.get(team_id)
    profile_photo = team.profile_photo if team else None
    if not pseudonym and team:
        pseudonym = team.name
    if not pseudonym:
        pseudonym = team_id
    shortname = reg.shortname if (reg and reg.shortname) else None
    return pseudonym, profile_photo, shortname


@bp.route("/tournaments/<tournament_url>/results", methods=["GET"])
def tournament_results(tournament_url):
    """Tournament results: teams with aggregate stats (no per-match data)."""
    from app.services.team_stats_service import compute_team_stats

    tournament, err = _require_tournament(tournament_url)
    if err:
        return jsonify({"error": "Not found"}), err
    matches = Match.query.filter(
        Match.event == tournament_url,
        Match.status.in_([MatchStatus.COMPLETED, MatchStatus.SKIPPED]),
    ).all()
    include_ribbon = request.args.get("include_ribbon", "").lower() in (
        "1",
        "true",
        "yes",
    )
    teams_list = compute_team_stats(matches, tournament, include_ribbon=include_ribbon)
    return jsonify({"tournament": _tournament_to_dict(tournament), "teams": teams_list})


@bp.route("/tournaments/<tournament_url>/results/team/<team_id>", methods=["GET"])
def tournament_results_team_matches(tournament_url, team_id):
    """Matches for one team in this tournament (for expandable row)."""
    tournament, err = _require_tournament(tournament_url)
    if err:
        return jsonify({"error": "Not found"}), err
    matches = (
        Match.query.filter(
            Match.event == tournament_url,
            Match.status.in_([MatchStatus.COMPLETED, MatchStatus.SKIPPED]),
            (Match.team1 == team_id) | (Match.team2 == team_id),
        )
        .order_by(Match.completed_time, Match.uuid)
        .all()
    )
    match_ids = [m.uuid for m in matches]
    points_by_match = {}
    if match_ids:
        for p in Point.query.filter(Point.match.in_(match_ids)).all():
            points_by_match.setdefault(p.match, []).append(p)
    match_list = []
    for m in matches:
        team1_name = _team_name_for_match(tournament, m, "team1")
        team2_name = _team_name_for_match(tournament, m, "team2")
        points_list = points_by_match.get(m.uuid, [])
        set_scores = {}
        for p in points_list:
            if getattr(p, "rerolled", False):
                continue
            sn = getattr(p, "set_number", None) or 1
            set_scores.setdefault(sn, {"set_number": sn, "team1_points": 0, "team2_points": 0})
            w = getattr(p, "winner", None)
            if w == "TEAM1":
                set_scores[sn]["team1_points"] += 1
            elif w == "TEAM2":
                set_scores[sn]["team2_points"] += 1
        sets_list = sorted(set_scores.values(), key=lambda x: x["set_number"])
        your_side = "TEAM1" if m.team1 == team_id else "TEAM2"
        match_list.append(
            {
                "uuid": m.uuid,
                "name": m.name,
                "team1_name": team1_name,
                "team2_name": team2_name,
                "match_winner": m.match_winner.value if m.match_winner else None,
                "your_side": your_side,
                "sets": sets_list,
                "ribbon": getattr(m, "ribbon", False),
            }
        )
    return jsonify({"matches": match_list})


@bp.route("/tournaments/<tournament_url>/fields", methods=["GET"])
def tournament_fields(tournament_url):
    """List fields for a tournament."""
    tournament, err = _require_tournament(tournament_url)
    if err:
        return jsonify({"error": "Not found"}), err
    fields = Field.query.filter_by(event=tournament_url).order_by(Field.name).all()
    return jsonify({"fields": [{"id": f.id, "name": f.name, "camera": f.camera} for f in fields]})


@bp.route("/tournaments/<tournament_url>/schedule-setup", methods=["GET"])
def tournament_schedule_setup(tournament_url):
    """
    Combined schedule and setup data for the unified page.
    Returns tournament, matches (full details), fields, tags, team_options, etc.
    Overlap/conflict detection is done in the frontend.
    """
    tournament, err = _require_tournament(tournament_url)
    if err:
        return jsonify({"error": "Not found"}), err

    is_to = _check_to(tournament_url)
    if not _schedule_published_check(tournament_url, tournament) and not is_to:
        return jsonify({"error": "Schedule not published"}), 403

    # Fields
    fields_query = Field.query.filter_by(event=tournament_url).order_by(Field.name).all()
    fields_data = []
    for f in fields_query:
        camera_urls = []
        if f.camera:
            try:
                loaded = json.loads(f.camera)
                if isinstance(loaded, list):
                    camera_urls = loaded
                else:
                    camera_urls = [f.camera]
            except:
                camera_urls = [f.camera]
        fields_data.append({"id": f.id, "name": f.name, "camera_urls": camera_urls})

    # Tags
    tags_query = Tag.query.filter_by(event=tournament_url).order_by(Tag.name).all()
    tags_data = [{"id": t.id, "name": t.name, "team": t.team} for t in tags_query]

    # Matches
    matches_query = Match.query.filter_by(event=tournament_url).order_by(Match.nominal_start_time).all()
    match_list = []
    for m in matches_query:
        match_list.append(
            {
                "uuid": m.uuid,
                "name": m.name,
                "field": m.field,
                "team1": m.team1,
                "team2": m.team2,
                "team1_initial": m.team1_initial,
                "team2_initial": m.team2_initial,
                "status": (m.status.value if hasattr(m.status, "value") else str(m.status)),
                "nominal_start_time": _dt_iso(m.nominal_start_time),
                "confirmed_start_time": _dt_iso(m.confirmed_start_time),
                "completed_time": _dt_iso(m.completed_time),
                "schedule_type": m.schedule_type.value if m.schedule_type else None,
                "set_type": m.set_type.value if m.set_type else None,
                "nominal_length": m.nominal_length,
                "previous_match": m.previous_match,
                "next_match": m.next_match,
                "refs": get_match_refs_csv(m) or None,
                "refs_initial": get_match_refs_initial_csv(m) or None,
                "ribbon": m.ribbon,
                "skip_condition": m.skip_condition,
                "nsets": m.nsets,
                "stones_per_set": m.stones_per_set,
                "stones_remaining": m.stones_remaining,
                "match_winner": m.match_winner.value if m.match_winner else None,
            }
        )

    # Team Options: only teams with valid (confirmed) registration for this tournament.
    # Create/edit match modals use this; match refs (MatchName::winner/loser) and tags (tag::Name) are offered separately.
    team_options = []
    seen = set()
    from app.services.registration_resolver import team_registrations_for_tournament

    for tr in team_registrations_for_tournament(tournament):
        if tr.team not in seen:
            team = Team.query.get(tr.team)
            team_options.append(
                {
                    "id": tr.team,
                    "pseudonym": tr.pseudonym,
                    "shortname": tr.shortname,
                    "profile_photo": team.profile_photo if team else None,
                }
            )
            seen.add(tr.team)

    return jsonify(
        {
            "tournament": _tournament_to_dict(tournament),
            "matches": match_list,
            "fields": fields_data,
            "tags": tags_data,
            "team_options": team_options,
            "is_to": is_to,
        }
    )


def _team_name_for_match(tournament, match, team_key):
    from app.services.registration_resolver import team_registration_for_tournament

    team_id = getattr(match, team_key)
    if not team_id:
        initial = getattr(match, f"{team_key}_initial", None)
        return initial or f"Team {team_key[-1]}"
    reg = team_registration_for_tournament(tournament, team_id)
    if reg and reg.pseudonym:
        return reg.pseudonym
    t = Team.query.get(team_id)
    return t.name if t else team_id


def _team_display_name(tournament, team_id):
    """Resolve a team id to display name (pseudonym preferred, else team name)."""
    from app.services.registration_resolver import team_registration_for_tournament

    if not team_id or not str(team_id).strip():
        return None
    reg = team_registration_for_tournament(tournament, team_id)
    if reg and reg.pseudonym:
        return reg.pseudonym
    t = Team.query.get(team_id)
    return t.name if t else team_id


def _refs_display_for_match(tournament, match):
    """Refs as comma-separated display names (pseudonym for each ref team), like team1_name/team2_name."""
    team_ids = get_match_ref_team_ids(match)
    initials_csv = get_match_refs_initial_csv(match) or None
    if not any(team_ids):
        return initials_csv
    parts = []
    for tid in team_ids:
        tid = tid.strip()
        if not tid:
            continue
        name = _team_display_name(tournament, tid)
        if name:
            parts.append(name)
    return ",".join(parts) if parts else initials_csv


@bp.route("/tournaments/<tournament_url>/match", methods=["GET"])
def tournament_match_detail(tournament_url):
    """Match detail by id= or name=. Returns match metadata and points."""
    tournament, err = _require_tournament(tournament_url)
    if err:
        return jsonify({"error": "Not found"}), err
    from app.utils.helpers import match_event_urls_for_penalties

    event_urls = match_event_urls_for_penalties(tournament)
    match_id = request.args.get("id", "").strip()
    match_name = request.args.get("name", "").strip()
    if not match_id and not match_name:
        return jsonify({"error": "Match id or name required"}), 400
    if match_id:
        match = Match.query.filter(Match.uuid == match_id, Match.event.in_(event_urls)).first()
    else:
        match = Match.query.filter(Match.name == match_name, Match.event.in_(event_urls)).first()
    if not match:
        return jsonify({"error": "Match not found"}), 404
    points = Point.query.filter_by(match=match.uuid).order_by(Point.stamp).all()
    team1_name = _team_name_for_match(tournament, match, "team1")
    team2_name = _team_name_for_match(tournament, match, "team2")
    _, team1_photo, team1_shortname = _team_pseudonym_and_photo(tournament, match.team1)
    _, team2_photo, team2_shortname = _team_pseudonym_and_photo(tournament, match.team2)
    points_data = [
        {
            "uuid": p.uuid,
            "set_number": p.set_number,
            "winner": p.winner,
            "rerolled": p.rerolled,
            "stamp": _dt_iso(p.stamp),
            "end_stamp": _dt_iso(p.end_stamp),
            "stones_at_start": (p.stones_at_start if match.set_type == SetType.STONES else None),
        }
        for p in points
    ]

    # Get camera data. New sources come from the `Camera` table; legacy
    # recorded point timestamps are read from `Match.camera_stream_starts`.
    available_cameras = []
    camera_url = None
    from app.utils.camera_helpers import parse_camera_urls

    legacy_point_timestamps_by_camera_name = {}
    if match.camera_stream_starts:
        try:
            legacy_data = json.loads(match.camera_stream_starts) or {}
            if isinstance(legacy_data, dict):
                for cam_name, recording_data in legacy_data.items():
                    if isinstance(recording_data, dict):
                        pts = recording_data.get("point_timestamps")
                        if pts is not None:
                            legacy_point_timestamps_by_camera_name[cam_name] = pts
        except (json.JSONDecodeError, TypeError):
            pass

    # 1) YouTube livestream cameras from Field configuration (source of truth initially).
    camera_urls: list[str] = []
    if match.field:
        field_obj = Field.query.filter_by(event=tournament_url, name=match.field).first()
        if field_obj and field_obj.camera:
            camera_urls = parse_camera_urls(field_obj.camera)
            for idx, url in enumerate(camera_urls):
                available_cameras.append(
                    {
                        "index": idx,
                        "url": url,
                        "stream_start_time": None,
                        "type": "youtube",
                        "status": "SUCCESS",
                    }
                )

    # 2) Match-scoped cameras from the new Camera table.
    camera_rows = (
        Camera.query.filter_by(match_uuid=match.uuid).filter_by(event=tournament_url).order_by(Camera.name.asc()).all()
    )
    for idx, cam in enumerate(camera_rows):
        cam_type = "youtube" if (cam.source_type or "").strip() == "youtube_livestream" else "recorded"
        worlds, videos = get_camera_timepoint_arrays(cam)
        time_world = worlds or None
        time_video = videos or None

        # Only provide YouTube URL/id once upload succeeded.
        url = cam.link if cam.status == "SUCCESS" else None

        # FAILED downloads:
        # - if `file` is a local static/ path, frontend can link directly
        # - if `file` looks like an S3 key, return a presigned URL instead
        video_path = cam.file
        if cam.status == "FAILED" and video_path and not video_path.startswith("static/"):
            bucket = current_app.config.get("S3_VIDEO_BUCKET")
            if bucket:
                from app.utils.s3_video import get_presigned_url

                region = (current_app.config.get("AWS_REGION") or "us-east-1") or "us-east-1"
                expiry = current_app.config.get("S3_PRESIGNED_EXPIRY_SECONDS", 3600)
                endpoint_url = current_app.config.get("S3_ENDPOINT_URL")
                playable_url = get_presigned_url(
                    bucket,
                    video_path,
                    region=region,
                    expiry_seconds=expiry,
                    endpoint_url=endpoint_url,
                )
                if playable_url:
                    video_path = playable_url

        available_cameras.append(
            {
                "index": len(camera_urls) + idx,
                "url": url,
                "stream_start_time": None,
                "type": cam_type,
                "video_path": video_path,
                "camera_id": cam.name,
                "session_id": None,
                "point_timestamps": legacy_point_timestamps_by_camera_name.get(cam.name),
                "status": cam.status,
                "source_type": cam.source_type,
                "time_world": time_world,
                "time_video": time_video,
            }
        )

    if available_cameras:
        first_cam = available_cameras[0]
        if first_cam.get("type") == "youtube":
            camera_url = first_cam.get("url")

    can_retry_finalization = current_user_can_retry_finalization(current_user)

    # Get match notes
    initial_notes = match.initial_notes or ""
    final_notes = match.final_notes or ""
    match_notes = []
    point_notes_map = {}

    # Check if user is head ref
    is_head_ref = False
    if current_user.is_authenticated:
        if is_player(current_user):
            is_head_ref = can_head_ref_match(tournament_url, current_user.id, match=match)

    # Can start and blocking reasons (for "why?" UX)
    from app.services.match_start_eligibility import (
        get_can_start_and_reasons,
        get_conflicting_match_on_field,
        why_sections_to_dict,
    )

    _user = current_user if current_user.is_authenticated else None
    can_start, block_reasons, why_sections = get_can_start_and_reasons(tournament_url, match, _user)

    # Conflicting match on same field (for force-start modal)
    conflicting_match = None
    other_match = get_conflicting_match_on_field(tournament_url, match)
    if other_match:
        from app.services.registration_resolver import team_registration_for_tournament

        reg1 = team_registration_for_tournament(tournament, other_match.team1) if other_match.team1 else None
        reg2 = team_registration_for_tournament(tournament, other_match.team2) if other_match.team2 else None
        conflicting_match = {
            "uuid": other_match.uuid,
            "name": getattr(other_match, "name", other_match.uuid),
            "team1_name": _team_name_for_match(tournament, other_match, "team1"),
            "team2_name": _team_name_for_match(tournament, other_match, "team2"),
            "team1_shortname": reg1.shortname if reg1 else None,
            "team2_shortname": reg2.shortname if reg2 else None,
        }

    # Get match-level notes (point_id is None) - only for head refs
    if is_head_ref:
        notes = MatchNote.query.filter_by(match=match.uuid, point_id=None).order_by(MatchNote.created_at.desc()).all()
        from app.utils.player_helpers import get_player_display_name

        for note in notes:
            player_name = None
            player_display = None
            if note.player_id:
                player_name, player_display = get_player_display_name(note.player_id, tournament_url)
            team_id = None
            if note.target == "team1":
                team_id = match.team1
            elif note.target == "team2":
                team_id = match.team2

            match_notes.append(
                {
                    "text": note.text,
                    "target": note.target,
                    "player_id": note.player_id,
                    "player_name": player_name,
                    "player_display": player_display,
                    "team_id": team_id,
                    "created_at": _dt_iso(note.created_at),
                }
            )

    # Build match_players for player-targeted notes (jersey/name search + profile photo)
    match_players = []
    from app.utils.player_helpers import get_player_display_from_registration

    # Parse selected players for "in_this_match" check
    team1_selected = set(get_match_player_ids(match, WinnerSide.TEAM1))
    team2_selected = set(get_match_player_ids(match, WinnerSide.TEAM2))

    # Helper to add players from a team (registration). Skip any player whose id is in exclude_ids (e.g. playing for the other team).
    def add_team_players(team_id, team_side, selected_ids, exclude_ids=None):
        exclude_ids = exclude_ids or set()
        if not team_id:
            return
        regs = PlayerRegistration.query.filter_by(
            event=tournament_url,
            team=team_id,
            status=RegistrationStatus.CONFIRMED,
        ).all()

        for pr in regs:
            if pr.player in exclude_ids:
                continue
            player = Player.query.get(pr.player)
            if player:
                display = get_player_display_from_registration(player, pr)
                match_players.append(
                    {
                        "player_id": player.id,
                        "name": player.name or "",
                        "display": display,
                        "profile_photo": getattr(player, "profile_photo", None),
                        "team_side": team_side,
                        "in_this_match": player.id in selected_ids,
                    }
                )

    # Team1: don't list players who are playing for team2 (in team2_selected).
    add_team_players(match.team1, "team1", team1_selected, exclude_ids=team2_selected)
    # Team2: don't list players who are playing for team1 (in team1_selected).
    add_team_players(match.team2, "team2", team2_selected, exclude_ids=team1_selected)

    # Include players who are in team2_selected but not on team2's roster (added via search on start-match).
    existing_player_ids = {p["player_id"] for p in match_players}
    for pid in team2_selected:
        if pid in existing_player_ids:
            continue
        player = Player.query.get(pid)
        if player:
            pr = PlayerRegistration.query.filter_by(
                event=tournament_url,
                player=pid,
                status=RegistrationStatus.CONFIRMED,
            ).first()
            display = get_player_display_from_registration(player, pr) if pr else (player.name or pid)
            match_players.append(
                {
                    "player_id": player.id,
                    "name": player.name or "",
                    "display": display,
                    "profile_photo": getattr(player, "profile_photo", None),
                    "team_side": "team2",
                    "in_this_match": True,
                }
            )
            existing_player_ids.add(pid)
    # Same for team1_selected: players added via search to team1 only.
    for pid in team1_selected:
        if pid in existing_player_ids:
            continue
        player = Player.query.get(pid)
        if player:
            pr = PlayerRegistration.query.filter_by(
                event=tournament_url,
                player=pid,
                status=RegistrationStatus.CONFIRMED,
            ).first()
            display = get_player_display_from_registration(player, pr) if pr else (player.name or pid)
            match_players.append(
                {
                    "player_id": player.id,
                    "name": player.name or "",
                    "display": display,
                    "profile_photo": getattr(player, "profile_photo", None),
                    "team_side": "team1",
                    "in_this_match": True,
                }
            )
            existing_player_ids.add(pid)

    # Calculate penalty counts for match players
    player_ids_in_match = [p["player_id"] for p in match_players]
    penalty_counts_map = {}

    if player_ids_in_match:
        # Count per player and penalty type (league: all matches in league; standalone: this event only)
        results = (
            db.session.query(
                MatchNote.player_id,
                MatchNote.penalty_type_id,
                func.count(MatchNote.uuid),
            )
            .join(Match)
            .filter(
                Match.event.in_(event_urls),
                MatchNote.target == "player",
                MatchNote.player_id.in_(player_ids_in_match),
            )
            .group_by(MatchNote.player_id, MatchNote.penalty_type_id)
            .all()
        )

        for pid, pt_id, count in results:
            if pid not in penalty_counts_map:
                penalty_counts_map[pid] = {}
            # Key: penalty_type_id (or "other" if None) -> count
            key = str(pt_id) if pt_id is not None else "other"
            penalty_counts_map[pid][key] = count

    # Add counts to match_players
    for p in match_players:
        p["penalty_counts"] = penalty_counts_map.get(p["player_id"], {})

    # Sort: in_this_match first, then by name
    match_players.sort(key=lambda p: (not p["in_this_match"], p["display"]))

    # Get penalty types (league's if league event, else event's)
    from app.utils.helpers import get_penalty_types_for_tournament

    penalty_types = get_penalty_types_for_tournament(tournament)
    penalty_types_data = [{"id": t.id, "name": t.name, "color": t.color, "desc": (t.desc or "")} for t in penalty_types]

    # Get point-specific notes - point notes (target='match') visible to everyone
    if points:
        point_ids = [p.uuid for p in points]
        if point_ids:
            point_notes_query = (
                MatchNote.query.filter_by(match=match.uuid)
                .filter(MatchNote.point_id.in_(point_ids))
                .order_by(MatchNote.created_at.asc())
            )
            if not is_head_ref:
                point_notes_query = point_notes_query.filter_by(target="match")

            point_notes = point_notes_query.all()
            from app.utils.player_helpers import get_player_display_name

            for n in point_notes:
                if not is_head_ref and n.target != "match":
                    continue

                player_name = None
                player_display = None
                if n.player_id:
                    player_name, player_display = get_player_display_name(n.player_id, tournament_url)
                team_id = None
                if n.target == "team1":
                    team_id = match.team1
                elif n.target == "team2":
                    team_id = match.team2

                point_notes_map.setdefault(n.point_id, []).append(
                    {
                        "text": n.text,
                        "target": n.target,
                        "player_id": n.player_id,
                        "player_name": player_name,
                        "player_display": player_display,
                        "team_id": team_id,
                        "created_at": _dt_iso(n.created_at),
                        "penalty_type_id": getattr(n, "penalty_type_id", None),
                    }
                )

    return jsonify(
        {
            "match": {
                "uuid": match.uuid,
                "name": match.name,
                "field": match.field,
                "team1": match.team1,
                "team2": match.team2,
                "team1_name": team1_name,
                "team2_name": team2_name,
                "team1_photo": team1_photo,
                "team2_photo": team2_photo,
                "team1_shortname": team1_shortname,
                "team2_shortname": team2_shortname,
                "team1_initial": match.team1_initial,
                "team2_initial": match.team2_initial,
                "status": (match.status.value if hasattr(match.status, "value") else str(match.status)),
                "nominal_start_time": _dt_iso(match.nominal_start_time),
                "confirmed_start_time": _dt_iso(match.confirmed_start_time),
                "completed_time": _dt_iso(match.completed_time),
                "set_type": match.set_type.value if match.set_type else None,
                "stones_per_set": match.stones_per_set,
                "stones_remaining": match.stones_remaining,
                "match_winner": (match.match_winner.value if match.match_winner else None),
                "schedule_type": (match.schedule_type.value if match.schedule_type else None),
                "nominal_length": match.nominal_length,
                "previous_match": match.previous_match,
                "refs": get_match_refs_csv(match) or None,
                "refs_initial": get_match_refs_initial_csv(match) or None,
                "refs_display": _refs_display_for_match(tournament, match),
                "ribbon": match.ribbon,
                "skip_condition": match.skip_condition,
                "nsets": match.nsets,
                "initial_notes": initial_notes,
                "final_notes": final_notes,
            },
            "points": points_data,
            "available_cameras": available_cameras,
            "camera_url": camera_url,
            "match_notes": match_notes,
            "point_notes_map": point_notes_map,
            "is_head_ref": is_head_ref,
            "can_retry_finalization": can_retry_finalization,
            "can_start": can_start,
            "block_reasons": block_reasons,
            "why_sections": why_sections_to_dict(why_sections),
            "conflicting_match": conflicting_match,
            "match_players": match_players,
            "penalty_types": penalty_types_data,
        }
    )


@bp.route("/tournaments/<tournament_url>/match-state", methods=["GET"])
def tournament_match_state(tournament_url):
    """Get current match state for polling (CORS-friendly). Public endpoint."""
    match_id = request.args.get("match_id") or request.args.get("id")
    if not match_id:
        return jsonify({"error": "Match ID required"}), 400

    match = Match.query.filter_by(uuid=match_id, event=tournament_url).first()
    if not match:
        return jsonify({"error": "Match not found"}), 404

    points = Point.query.filter_by(match=match.uuid).order_by(Point.stamp).all()

    team1_score = sum(1 for p in points if p.winner == "TEAM1" and not p.rerolled)
    team2_score = sum(1 for p in points if p.winner == "TEAM2" and not p.rerolled)

    sets = sorted(set(p.set_number for p in points))
    scores_by_set = {}
    for set_num in sets:
        set_points = [p for p in points if p.set_number == set_num]
        scores_by_set[set_num] = {
            "team1_score": sum(1 for p in set_points if p.winner == "TEAM1" and not p.rerolled),
            "team2_score": sum(1 for p in set_points if p.winner == "TEAM2" and not p.rerolled),
        }

    points_data = []
    for p in points:
        stamp_iso = to_iso_z(p.stamp).unwrap_or(None)
        end_stamp_iso = to_iso_z(p.end_stamp).unwrap_or(None)
        points_data.append(
            {
                "uuid": p.uuid,
                "set_number": p.set_number,
                "winner": p.winner,
                "rerolled": p.rerolled,
                "stamp": stamp_iso,
                "end_stamp": end_stamp_iso,
                "stones_at_start": (p.stones_at_start if match.set_type == SetType.STONES else None),
            }
        )

    finalized_at = None
    if match.status in (MatchStatus.COMPLETED, MatchStatus.SKIPPED) and match.finalized_at:
        finalized_at = match.finalized_at.isoformat()

    return jsonify(
        {
            "match_id": match.uuid,
            "status": (match.status.value if hasattr(match.status, "value") else str(match.status)),
            "team1_score": team1_score,
            "team2_score": team2_score,
            "scores_by_set": scores_by_set,
            "points": points_data,
            "stones_remaining": (
                match.stones_remaining if getattr(match, "set_type", None) == SetType.STONES else None
            ),
            "finalized_at": finalized_at,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )


@bp.route("/tournaments/<tournament_url>/matches/<match_id>", methods=["PUT"])
@login_required
def update_match_api(tournament_url, match_id):
    if not _check_to(tournament_url):
        return jsonify({"error": "Forbidden"}), 403

    match = Match.query.filter_by(uuid=match_id, event=tournament_url).first_or_404()
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400

    # Allowed schedule type transitions when editing (only these target types are allowed from each source)
    _ALLOWED_SCHEDULE_TYPE_TRANSITIONS = {
        ScheduleType.STATIC: (
            ScheduleType.STATIC,
            ScheduleType.SAFE,
            ScheduleType.FAST,
        ),
        ScheduleType.SAFE: (ScheduleType.SAFE, ScheduleType.FAST),
        ScheduleType.FAST: (ScheduleType.FAST,),
        ScheduleType.BREAK: (ScheduleType.BREAK,),
        ScheduleType.JOIN: (ScheduleType.JOIN,),
    }

    # Extract fields
    name = data.get("name")
    field = data.get("field")
    schedule_type_str = data.get("schedule_type")  # STATIC, SAFE, FAST, BREAK, JOIN
    length = data.get("length")
    start_time_str = data.get("start_time")
    previous_match_id = data.get("previous_match_id")
    refs = data.get("refs")  # list of strings
    team1_input = data.get("team1")
    team2_input = data.get("team2")
    set_type_str = data.get("set_type")  # SETS, STONES
    nsets = data.get("nsets")
    stones_per_set = data.get("stones_per_set")
    ribbon = data.get("ribbon")
    skip_condition = data.get("skip_condition")

    # Schedule Type (apply first so name uniqueness uses the new type)
    if schedule_type_str:
        try:
            new_schedule_type = ScheduleType(schedule_type_str)
            current_schedule_type = match.schedule_type
            allowed = _ALLOWED_SCHEDULE_TYPE_TRANSITIONS.get(current_schedule_type, (current_schedule_type,))
            if new_schedule_type not in allowed:
                return (
                    jsonify(
                        {
                            "error": f"Match type cannot be changed from {current_schedule_type.value} to {new_schedule_type.value}. "
                            "Allowed changes: Static→Safe/Fast, Safe→Fast only."
                        }
                    ),
                    400,
                )
            match.schedule_type = new_schedule_type
        except ValueError:
            pass  # Ignore invalid enum

    # Validate inputs
    if name:
        mn_err = match_name_char_error(name.strip())
        if mn_err:
            return jsonify({"error": mn_err}), 400
        match.name = name
    if field is not None:  # field can be empty string/null
        match.field = field

    # Match name uniqueness: for BREAK/JOIN only within same field; for others globally in tournament
    if name is not None or field is not None:
        effective_name = (match.name or "").strip()
        effective_field = (match.field or "").strip()
        if effective_name:
            if match.schedule_type in (ScheduleType.BREAK, ScheduleType.JOIN):
                existing_name = (
                    Match.query.filter_by(
                        event=tournament_url,
                        name=effective_name,
                        field=effective_field,
                        schedule_type=match.schedule_type,
                    )
                    .filter(Match.uuid != match.uuid)
                    .first()
                )
            else:
                existing_name = (
                    Match.query.filter_by(event=tournament_url, name=effective_name)
                    .filter(Match.uuid != match.uuid)
                    .first()
                )
            if existing_name:
                if match.schedule_type in (ScheduleType.BREAK, ScheduleType.JOIN):
                    return (
                        jsonify(
                            {
                                "error": f"A {match.schedule_type.value} match with this name already exists on this field."
                            }
                        ),
                        400,
                    )
                return (
                    jsonify({"error": "A match with this name already exists in this tournament."}),
                    400,
                )

    # Handle BREAK/JOIN clearing teams
    if match.schedule_type in (ScheduleType.BREAK, ScheduleType.JOIN):
        match.team1 = None
        match.team1_initial = None
        match.team2 = None
        match.team2_initial = None
        clear_match_referees(match)
    else:
        # Helper to check if a value is an explicit team ID (not a tag or match reference)
        def is_explicit_team_id(val: str) -> bool:
            if not val or not val.strip():
                return False
            val = val.strip()
            # Not a tag reference
            if val.lower().startswith("tag::"):
                return False
            # Not a match reference (contains ::winner or ::loser)
            if "::winner" in val.lower() or "::loser" in val.lower():
                return False
            # Must be an explicit team ID
            return True

        # Teams (helper takes team_name first, then tournament_url)
        if team1_input is not None:
            team1_name = str(team1_input).strip()
            if not team1_name:
                match.team1 = None
                match.team1_initial = None
            else:
                t1_id, _ = resolve_team_name_to_id(team1_name, tournament_url)
                final_team1 = None
                if t1_id:
                    final_team1 = t1_id
                elif is_explicit_team_id(team1_name):
                    final_team1 = team1_name
                else:
                    resolved_team = resolve_tag_to_team(team1_name, tournament_url)
                    if resolved_team:
                        final_team1 = resolved_team
                match.team1 = final_team1
                match.team1_initial = team1_name

        if team2_input is not None:
            team2_name = str(team2_input).strip()
            if not team2_name:
                match.team2 = None
                match.team2_initial = None
            else:
                t2_id, _ = resolve_team_name_to_id(team2_name, tournament_url)
                final_team2 = None
                if t2_id:
                    final_team2 = t2_id
                elif is_explicit_team_id(team2_name):
                    final_team2 = team2_name
                else:
                    resolved_team = resolve_tag_to_team(team2_name, tournament_url)
                    if resolved_team:
                        final_team2 = resolved_team
                match.team2 = final_team2
                match.team2_initial = team2_name

        # Refs: parallel refs / refs_initial (same slot count)
        if refs is not None:
            if isinstance(refs, list):
                r_csv, i_csv = resolve_refs_slots(refs, tournament_url)
            else:
                toks = refs_string_to_tokens(refs)
                r_csv, i_csv = resolve_refs_slots(toks, tournament_url)
            set_match_referees_from_csv(match, r_csv, i_csv)

    # Set Type
    if set_type_str:
        try:
            match.set_type = SetType(set_type_str)
        except ValueError:
            pass

    if nsets is not None:
        match.nsets = int(nsets)

    if stones_per_set is not None:
        match.stones_per_set = int(stones_per_set)

    if ribbon is not None:
        match.ribbon = bool(ribbon)

    # Length
    if match.schedule_type == ScheduleType.JOIN:
        match.nominal_length = 0
    elif length is not None:
        match.nominal_length = int(length)

    # Skip Condition (only for SAFE/FAST)
    if skip_condition is not None:
        match.skip_condition = (
            (skip_condition.strip() if skip_condition.strip() else None)
            if match.schedule_type in (ScheduleType.SAFE, ScheduleType.FAST)
            else None
        )

    # Clear stones_per_set for non-STONES
    if match.set_type != SetType.STONES:
        match.stones_per_set = None

    # BREAK, JOIN, FAST, SAFE require non-empty previous_match on same field
    if match.schedule_type in (
        ScheduleType.BREAK,
        ScheduleType.JOIN,
        ScheduleType.FAST,
        ScheduleType.SAFE,
    ):
        prev_id = (previous_match_id or "").strip() if previous_match_id is not None else ""
        if not prev_id:
            return (
                jsonify({"error": "Previous match is required for Break, Join, Fast, and Safe matches."}),
                400,
            )
        effective_field = match.field or ""
        if not effective_field:
            return (
                jsonify({"error": "Field is required when using a previous match."}),
                400,
            )
        prev_match = Match.query.filter_by(uuid=prev_id, event=tournament_url).first()
        if not prev_match:
            return jsonify({"error": "Previous match not found."}), 400
        prev_field = (prev_match.field or "").strip()
        if prev_field != effective_field.strip():
            return jsonify({"error": "Previous match must be on the same field."}), 400

    # Scheduling Logic
    from datetime import datetime, timezone

    if match.schedule_type == ScheduleType.STATIC:
        if start_time_str:
            try:
                # Handle ISO format (potentially with Z or offset)
                dt = datetime.fromisoformat(start_time_str.replace("Z", "+00:00"))
                # Ensure naive UTC
                if dt.tzinfo:
                    dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
                match.nominal_start_time = dt
            except ValueError:
                pass

        # STATIC matches have no previous_match: always clear and unlink (ignore previous_match_id)
        if match.previous_match:
            old_prev = Match.query.filter_by(uuid=match.previous_match, event=tournament_url).first()
            if old_prev and old_prev.next_match == match.uuid:
                old_prev.next_match = match.next_match
                if match.next_match:
                    old_next = Match.query.filter_by(uuid=match.next_match, event=tournament_url).first()
                    if old_next:
                        old_next.previous_match = old_prev.uuid
            elif match.next_match:
                old_next = Match.query.filter_by(uuid=match.next_match, event=tournament_url).first()
                if old_next:
                    old_next.previous_match = None
        match.previous_match = None  # Always set for STATIC so it persists
        flag_modified(match, "previous_match")
    else:
        # Dynamic (BREAK, JOIN, FAST, SAFE)
        match.nominal_start_time = compute_dynamic_match_nominal_start_time(match, tournament_url)
        if match.schedule_type in (
            ScheduleType.BREAK,
            ScheduleType.JOIN,
            ScheduleType.FAST,
            ScheduleType.SAFE,
        ):
            if previous_match_id:
                update_match_previous_link(match, previous_match_id, tournament_url)
        else:
            match.previous_match = None

    ok, err = validate_match_input(match, tournament_url)
    if not ok:
        db.session.rollback()
        return jsonify({"error": err}), 400

    db.session.flush()  # Emit UPDATE for previous_match etc. before commit
    db.session.commit()

    # Recompute all times
    recompute_all_match_times(tournament_url)

    return jsonify({"success": True})


@bp.route(
    "/tournaments/<tournament_url>/matches/<match_id>/force-start",
    methods=["POST"],
)
@login_required
def force_start_match_api(tournament_url, match_id):
    """Force-start a match: resolve teams/refs, handle conflicting match, convert to static."""
    from app.services.match_start_eligibility import get_conflicting_match_on_field

    match = Match.query.filter_by(uuid=match_id, event=tournament_url).first_or_404()
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400

    # Auth: require head ref
    if not current_user.is_authenticated:
        return jsonify({"error": "Must be logged in"}), 401
    if not is_player(current_user):
        return jsonify({"error": "Only player accounts can force start matches"}), 403
    if not can_head_ref_match(tournament_url, current_user.id, match=match):
        return jsonify({"error": "You are not allowed to head ref this match"}), 403

    team1_input = str(data.get("team1") or "").strip()
    team2_input = str(data.get("team2") or "").strip()
    refs_list = data.get("refs") or []
    if not isinstance(refs_list, list):
        refs_list = []
    conflicting_action = (data.get("conflicting_match_action") or "").strip()
    conflicting_winner = (data.get("conflicting_match_winner") or "").strip()

    # 1. Handle conflicting match (if any)
    other_match = get_conflicting_match_on_field(tournament_url, match)
    if other_match:
        if not conflicting_action:
            return (
                jsonify({"error": "Another match is in progress on this field. Choose SKIP or COMPLETE."}),
                400,
            )
        if conflicting_action == "COMPLETE" and conflicting_winner not in (
            "TEAM1",
            "TEAM2",
        ):
            return (
                jsonify({"error": "When marking as COMPLETE, choose TEAM1 or TEAM2 as winner."}),
                400,
            )

        now = now_utc_naive()
        # Close unfinished points on the conflicting match
        for pt in Point.query.filter_by(match=other_match.uuid).all():
            if pt.end_stamp is None:
                pt.end_stamp = now
        if conflicting_action == "SKIP":
            other_match.status = MatchStatus.SKIPPED
            other_match.match_winner = None
        else:
            other_match.status = MatchStatus.COMPLETED
            other_match.match_winner = WinnerSide.TEAM1 if conflicting_winner == "TEAM1" else WinnerSide.TEAM2
        other_match.finalized_at = now

    # 2. Update target match
    t1_id, t1_initial = resolve_team_slot(team1_input, tournament_url)
    t2_id, t2_initial = resolve_team_slot(team2_input, tournament_url)
    if not t1_id or not t2_id:
        return jsonify({"error": "Team 1 and Team 2 are required"}), 400

    match.team1 = t1_id
    match.team1_initial = t1_initial or team1_input
    match.team2 = t2_id
    match.team2_initial = t2_initial or team2_input

    # Refs: preserve slot count (registration, explicit id, tag)
    r_csv, i_csv = resolve_refs_slots(refs_list, tournament_url)
    set_match_referees_from_csv(match, r_csv, i_csv)

    # Convert to static
    match.schedule_type = ScheduleType.STATIC
    match.nominal_start_time = now_utc_naive()
    match.status = MatchStatus.READY_TO_START

    # Unlink previous/next
    if match.previous_match:
        old_prev = Match.query.filter_by(uuid=match.previous_match, event=tournament_url).first()
        if old_prev and old_prev.next_match == match.uuid:
            old_prev.next_match = match.next_match
            if match.next_match:
                old_next = Match.query.filter_by(uuid=match.next_match, event=tournament_url).first()
                if old_next:
                    old_next.previous_match = old_prev.uuid
        elif match.next_match:
            old_next = Match.query.filter_by(uuid=match.next_match, event=tournament_url).first()
            if old_next:
                old_next.previous_match = None
    match.previous_match = None
    match.next_match = None
    flag_modified(match, "previous_match")
    flag_modified(match, "next_match")

    db.session.flush()
    db.session.commit()
    recompute_all_match_times(tournament_url)

    return jsonify({"success": True})


def _check_to(tournament_url):
    if not current_user.is_authenticated:
        return False
    return PermissionService.is_tournament_organizer(tournament_url, current_user)


@bp.route("/tournaments/<tournament_url>/fields/<int:field_id>", methods=["GET"])
@login_required
def get_field(tournament_url, field_id):
    if not _check_to(tournament_url):
        return jsonify({"error": "Forbidden"}), 403
    field = Field.query.filter_by(id=field_id, event=tournament_url).first_or_404()

    # Parse camera JSON if needed, or return as is
    camera_urls = []
    if field.camera:
        try:
            data = json.loads(field.camera)
            if isinstance(data, list):
                camera_urls = data
            else:
                camera_urls = [field.camera]
        except:
            camera_urls = [field.camera]

    return jsonify({"id": field.id, "name": field.name, "camera_urls": camera_urls})


@bp.route("/tournaments/<tournament_url>/fields/<int:field_id>", methods=["PUT"])
@login_required
def update_field_api(tournament_url, field_id):
    if not _check_to(tournament_url):
        return jsonify({"error": "Forbidden"}), 403

    field = Field.query.filter_by(id=field_id, event=tournament_url).first_or_404()
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400

    new_field_name = data.get("name", "").strip()
    if not new_field_name:
        return jsonify({"error": "Field name required"}), 400

    old_field_name = field.name
    field.name = new_field_name

    camera_urls = [url for url in data.get("camera_urls", []) if url.strip()]
    old_camera_urls = []
    try:
        if field.camera:
            loaded = json.loads(field.camera)
            if isinstance(loaded, list):
                old_camera_urls = loaded
            else:
                old_camera_urls = [field.camera]
    except:
        if field.camera:
            old_camera_urls = [field.camera]

    field.camera = json.dumps(camera_urls) if camera_urls else ""

    # Update matches and points (logic copied from tournaments.py)
    field_name_for_query = old_field_name if old_field_name != new_field_name else new_field_name
    matches_to_update = Match.query.filter_by(event=tournament_url, field=field_name_for_query).all()

    camera_urls_changed = old_camera_urls != camera_urls

    if camera_urls_changed:
        old_to_new_index_map = {}
        for new_idx, new_url in enumerate(camera_urls):
            try:
                old_idx = old_camera_urls.index(new_url)
                old_to_new_index_map[str(old_idx)] = str(new_idx)
            except ValueError:
                pass

        for match in matches_to_update:
            if match.camera_stream_starts:
                try:
                    stream_starts = json.loads(match.camera_stream_starts)
                    new_stream_starts = {}
                    for old_idx_str, start_time in stream_starts.items():
                        if old_idx_str in old_to_new_index_map:
                            new_idx_str = old_to_new_index_map[old_idx_str]
                            new_stream_starts[new_idx_str] = start_time
                    match.camera_stream_starts = json.dumps(new_stream_starts) if new_stream_starts else None
                except:
                    match.camera_stream_starts = None

        from app.utils.camera_helpers import calculate_stream_timestamp

        for match in matches_to_update:
            points = Point.query.filter_by(match=match.uuid).all()
            stream_starts = {}
            if match.camera_stream_starts:
                try:
                    stream_starts = json.loads(match.camera_stream_starts)
                except:
                    pass

            for point in points:
                if point.camera_index is not None:
                    old_idx_str = str(point.camera_index)
                    if old_idx_str in old_to_new_index_map:
                        point.camera_index = int(old_to_new_index_map[old_idx_str])
                    else:
                        # Try to find by URL
                        if point.camera_index < len(old_camera_urls):
                            old_url = old_camera_urls[point.camera_index]
                            try:
                                new_idx = camera_urls.index(old_url)
                                point.camera_index = new_idx
                            except ValueError:
                                point.camera_index = None
                                point.stream_timestamp = None
                        else:
                            point.camera_index = None
                            point.stream_timestamp = None

                if point.camera_index is not None and point.stamp:
                    camera_idx_str = str(point.camera_index)
                    if camera_idx_str in stream_starts:
                        new_ts = calculate_stream_timestamp(point.stamp, stream_starts[camera_idx_str])
                        if new_ts is not None:
                            point.stream_timestamp = new_ts

    if old_field_name != new_field_name:
        for match in matches_to_update:
            match.field = new_field_name

    # Optional: set stream start times for cameras (e.g. from YouTube API or user input).
    # Merge with existing: only update indices present in the request; never remove other keys.
    stream_start_times = data.get("stream_start_times")
    if stream_start_times is not None and isinstance(stream_start_times, list):
        from app.utils.camera_helpers import calculate_stream_timestamp

        for match in matches_to_update:
            stream_starts = {}
            if match.camera_stream_starts:
                try:
                    loaded = json.loads(match.camera_stream_starts)
                    if isinstance(loaded, dict):
                        stream_starts = dict(loaded)
                except (TypeError, ValueError):
                    pass
            for idx, val in enumerate(stream_start_times):
                if idx >= len(camera_urls):
                    break
                if val is not None and isinstance(val, str) and val.strip():
                    stream_starts[str(idx)] = val.strip()
                elif str(idx) in stream_starts:
                    del stream_starts[str(idx)]
            match.camera_stream_starts = json.dumps(stream_starts) if stream_starts else None
        # Recompute point stream_timestamp for matches we updated
        for match in matches_to_update:
            points = Point.query.filter_by(match=match.uuid).all()
            stream_starts = {}
            if match.camera_stream_starts:
                try:
                    stream_starts = json.loads(match.camera_stream_starts)
                except (TypeError, ValueError):
                    pass
            for point in points:
                if point.camera_index is not None and point.stamp and str(point.camera_index) in stream_starts:
                    new_ts = calculate_stream_timestamp(point.stamp, stream_starts[str(point.camera_index)])
                    if new_ts is not None:
                        point.stream_timestamp = new_ts

    db.session.commit()
    return jsonify({"success": True})


@bp.route("/tournaments/<tournament_url>/matches", methods=["POST"])
@login_required
def create_match_api(tournament_url):
    if not _check_to(tournament_url):
        return jsonify({"error": "Forbidden"}), 403

    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400

    name = data.get("name")
    if not name:
        return jsonify({"error": "Match name is required"}), 400
    mn_err = match_name_char_error(name.strip())
    if mn_err:
        return jsonify({"error": mn_err}), 400

    # Parse schedule type and field for name-uniqueness scope (BREAK/JOIN are unique per field)
    schedule_type_str = data.get("schedule_type")
    schedule_type = ScheduleType.STATIC
    if schedule_type_str:
        try:
            schedule_type = ScheduleType(schedule_type_str)
        except ValueError:
            pass
    effective_field = (data.get("field") or "").strip()

    # Name uniqueness: for BREAK/JOIN only within same field (and same type); for others globally in tournament
    if schedule_type in (ScheduleType.BREAK, ScheduleType.JOIN):
        existing = Match.query.filter_by(
            event=tournament_url,
            name=name.strip(),
            field=effective_field,
            schedule_type=schedule_type,
        ).first()
    else:
        existing = Match.query.filter_by(event=tournament_url, name=name.strip()).first()
    if existing:
        if schedule_type in (ScheduleType.BREAK, ScheduleType.JOIN):
            return (
                jsonify({"error": f"A {schedule_type.value} match with this name already exists on this field."}),
                400,
            )
        return jsonify({"error": "Match name already exists"}), 400

    match = Match(event=tournament_url, name=name)
    match.field = data.get("field")
    match.nominal_length = int(data.get("length")) if data.get("length") is not None else None
    match.schedule_type = schedule_type

    # BREAK, JOIN, FAST, SAFE require non-empty previous_match on same field
    if match.schedule_type in (
        ScheduleType.BREAK,
        ScheduleType.JOIN,
        ScheduleType.FAST,
        ScheduleType.SAFE,
    ):
        prev_id = (data.get("previous_match_id") or "").strip()
        if not prev_id:
            return (
                jsonify({"error": "Previous match is required for Break, Join, Fast, and Safe matches."}),
                400,
            )
        effective_field = (match.field or "").strip()
        if not effective_field:
            return (
                jsonify({"error": "Field is required when using a previous match."}),
                400,
            )
        prev_match = Match.query.filter_by(uuid=prev_id, event=tournament_url).first()
        if not prev_match:
            return jsonify({"error": "Previous match not found."}), 400
        prev_field = (prev_match.field or "").strip()
        if prev_field != effective_field:
            return jsonify({"error": "Previous match must be on the same field."}), 400

    if match.schedule_type == ScheduleType.STATIC:
        start_time_str = data.get("start_time")
        if start_time_str:
            try:
                dt = datetime.fromisoformat(start_time_str.replace("Z", "+00:00"))
                if dt.tzinfo:
                    dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
                match.nominal_start_time = dt
            except ValueError:
                pass

    # Helper to check if a value is an explicit team ID (not a tag or match reference)
    def is_explicit_team_id(val: str) -> bool:
        if not val or not val.strip():
            return False
        val = val.strip()
        # Not a tag reference
        if val.lower().startswith("tag::"):
            return False
        # Not a match reference (contains ::winner or ::loser)
        if "::winner" in val.lower() or "::loser" in val.lower():
            return False
        # Must be an explicit team ID
        return True

    # Team handling
    team1_input = data.get("team1") or ""
    team2_input = data.get("team2") or ""
    if match.schedule_type not in (ScheduleType.BREAK, ScheduleType.JOIN):
        # Normalize whitespace
        team1_name = str(team1_input).strip()
        team2_name = str(team2_input).strip()

        # Resolve via registrations (team ID or pseudonym) first
        team1_id, _ = resolve_team_name_to_id(team1_name, tournament_url) if team1_name else (None, None)
        team2_id, _ = resolve_team_name_to_id(team2_name, tournament_url) if team2_name else (None, None)

        # Derive final team1 from explicit IDs or tags when not resolved by registration
        final_team1 = None
        if team1_id:
            final_team1 = team1_id
        elif team1_name:
            if is_explicit_team_id(team1_name):
                final_team1 = team1_name
            else:
                resolved_team = resolve_tag_to_team(team1_name, tournament_url)
                if resolved_team:
                    final_team1 = resolved_team

        # Derive final team2 from explicit IDs or tags when not resolved by registration
        final_team2 = None
        if team2_id:
            final_team2 = team2_id
        elif team2_name:
            if is_explicit_team_id(team2_name):
                final_team2 = team2_name
            else:
                resolved_team = resolve_tag_to_team(team2_name, tournament_url)
                if resolved_team:
                    final_team2 = resolved_team

        match.team1 = final_team1
        match.team2 = final_team2
        match.team1_initial = team1_name or None
        match.team2_initial = team2_name or None

    # Refs: parallel refs / refs_initial (same slot count). Resolved here but
    # written below after the flush so the match has a uuid the join-table
    # rows can reference.
    refs = data.get("refs")
    refs_csv_pair: tuple[str, str] | None = None
    if refs and isinstance(refs, list):
        refs_csv_pair = resolve_refs_slots(refs, tournament_url)

    # Format
    set_type_str = data.get("set_type")
    if set_type_str:
        try:
            match.set_type = SetType(set_type_str)
        except ValueError:
            pass

    if data.get("nsets") is not None:
        match.nsets = int(data.get("nsets"))
    if match.set_type == SetType.STONES and data.get("stones_per_set") is not None:
        match.stones_per_set = int(data.get("stones_per_set"))

    if data.get("ribbon") is not None:
        match.ribbon = bool(data.get("ribbon"))

    match.skip_condition = data.get("skip_condition")

    db.session.add(match)
    db.session.flush()  # Ensure uuid exists before link updates and validation.

    if refs_csv_pair is not None:
        set_match_referees_from_csv(match, refs_csv_pair[0], refs_csv_pair[1])

    # Handle linked list insert
    prev_match_id = (
        data.get("previous_match_id")
        if match.schedule_type
        in (
            ScheduleType.SAFE,
            ScheduleType.FAST,
            ScheduleType.STATIC,
            ScheduleType.BREAK,
            ScheduleType.JOIN,
        )
        else None
    )
    if prev_match_id:
        update_match_previous_link(match, prev_match_id, tournament_url, is_new=True)

    # Dynamic time compute
    if match.schedule_type != ScheduleType.STATIC:
        match.nominal_start_time = compute_dynamic_match_nominal_start_time(match, tournament_url)

    ok, err = validate_match_input(match, tournament_url)
    if not ok:
        db.session.rollback()
        return jsonify({"error": err}), 400

    db.session.commit()

    # Recompute
    recompute_all_match_times(tournament_url)

    return jsonify({"success": True, "uuid": match.uuid})


@bp.route("/tournaments/<tournament_url>/matches/<match_id>", methods=["DELETE"])
@login_required
def delete_match_api(tournament_url, match_id):
    if not _check_to(tournament_url):
        return jsonify({"error": "Forbidden"}), 403

    match = Match.query.filter_by(uuid=match_id, event=tournament_url).first_or_404()

    # Update doubly linked list: unlink this match from prev and next
    if match.previous_match:
        prev = Match.query.filter_by(uuid=match.previous_match, event=tournament_url).first()
        if prev and prev.next_match == match.uuid:
            prev.next_match = match.next_match
    if match.next_match:
        nxt = Match.query.filter_by(uuid=match.next_match, event=tournament_url).first()
        if nxt and nxt.previous_match == match.uuid:
            nxt.previous_match = match.previous_match

    # Delete match notes and points first (they reference match)
    MatchNote.query.filter_by(match=match_id).delete(synchronize_session=False)
    Point.query.filter_by(match=match_id).delete(synchronize_session=False)

    db.session.delete(match)
    db.session.commit()
    recompute_all_match_times(tournament_url)

    return jsonify({"success": True})


@bp.route("/tournaments/<tournament_url>/fields", methods=["POST"])
@login_required
def create_field_api(tournament_url):
    if not _check_to(tournament_url):
        return jsonify({"error": "Forbidden"}), 403

    data = request.get_json()
    if not data or "name" not in data:
        return jsonify({"error": "Name required"}), 400

    name = data["name"].strip()
    if not name:
        return jsonify({"error": "Name required"}), 400

    if Field.query.filter_by(event=tournament_url, name=name).first():
        return jsonify({"error": "Field already exists"}), 400

    field = Field(event=tournament_url, name=name)
    camera_urls = [url for url in data.get("camera_urls", []) if url.strip()]
    if camera_urls:
        field.camera = json.dumps(camera_urls)

    db.session.add(field)
    db.session.commit()
    return jsonify({"success": True, "id": field.id})


@bp.route("/tournaments/<tournament_url>/fields/<int:field_id>", methods=["DELETE"])
@login_required
def delete_field_api(tournament_url, field_id):
    if not _check_to(tournament_url):
        return jsonify({"error": "Forbidden"}), 403

    field = Field.query.filter_by(id=field_id, event=tournament_url).first_or_404()

    # Check usage
    if Match.query.filter_by(event=tournament_url, field=field.name).first():
        return jsonify({"error": "Cannot delete field with matches"}), 400

    db.session.delete(field)
    db.session.commit()
    return jsonify({"success": True})


@bp.route("/tournaments/<tournament_url>/tags", methods=["POST"])
@login_required
def create_tag_api(tournament_url):
    if not _check_to(tournament_url):
        return jsonify({"error": "Forbidden"}), 403

    data = request.get_json()
    if not data or "name" not in data:
        return jsonify({"error": "Name required"}), 400

    name = data["name"].strip()
    if not name:
        return jsonify({"error": "Name required"}), 400
    if "::" in name:
        return jsonify({"error": 'Tag name cannot contain "::"'}), 400

    if Tag.query.filter_by(event=tournament_url, name=name).first():
        return jsonify({"error": "Tag already exists"}), 400

    tag = Tag(event=tournament_url, name=name)
    db.session.add(tag)
    db.session.commit()
    return jsonify({"success": True, "id": tag.id})


def _tag_usage(tournament_url, tag_name):
    """Return list of human-readable strings describing where tag is used, or empty if not used."""
    tag_ref = f"tag::{tag_name}"
    used = []
    for m in Match.query.filter_by(event=tournament_url).all():
        if m.team1_initial and m.team1_initial.strip() == tag_ref:
            used.append(f'Team 1 of match "{m.name}"')
        if m.team2_initial and m.team2_initial.strip() == tag_ref:
            used.append(f'Team 2 of match "{m.name}"')
        if any(initial == tag_ref for initial in get_match_ref_initials(m)):
            used.append(f'Refs of match "{m.name}"')
        if m.skip_condition and (tag_ref in m.skip_condition or tag_name in m.skip_condition):
            used.append(f'Skip condition of match "{m.name}"')
    return used


@bp.route("/tournaments/<tournament_url>/tags/<int:tag_id>", methods=["DELETE"])
@login_required
def delete_tag_api(tournament_url, tag_id):
    if not _check_to(tournament_url):
        return jsonify({"error": "Forbidden"}), 403

    tag = Tag.query.filter_by(id=tag_id, event=tournament_url).first_or_404()
    used = _tag_usage(tournament_url, tag.name)
    if used:
        return (
            jsonify(
                {
                    "error": f'Cannot delete tag "{tag.name}": it is used in '
                    + ", ".join(used[:5])
                    + (" (and possibly more)" if len(used) > 5 else "")
                }
            ),
            400,
        )
    db.session.delete(tag)
    db.session.commit()
    return jsonify({"success": True})


@login_required
def get_tag(tournament_url, tag_id):
    if not _check_to(tournament_url):
        return jsonify({"error": "Forbidden"}), 403
    tag = Tag.query.filter_by(id=tag_id, event=tournament_url).first_or_404()
    return jsonify({"id": tag.id, "name": tag.name})


@bp.route("/tournaments/<tournament_url>/tags/<int:tag_id>", methods=["PUT"])
@login_required
def update_tag_api(tournament_url, tag_id):
    if not _check_to(tournament_url):
        return jsonify({"error": "Forbidden"}), 403
    tag = Tag.query.filter_by(id=tag_id, event=tournament_url).first_or_404()
    data = request.get_json()
    if not data or "name" not in data:
        return jsonify({"error": "Name required"}), 400
    tag.name = data["name"]
    db.session.commit()
    return jsonify({"success": True})


@bp.route("/tournaments/<tournament_url>/tags", methods=["GET"])
@login_required
def list_tags(tournament_url):
    if not _check_to(tournament_url):
        return jsonify({"error": "Forbidden"}), 403
    tags = Tag.query.filter_by(event=tournament_url).order_by(Tag.name).all()
    return jsonify({"tags": [{"id": t.id, "name": t.name, "team": t.team} for t in tags]})


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


@bp.route("/tournaments/<tournament_url>/recompute-schedule", methods=["POST"])
@login_required
def recompute_schedule_api(tournament_url):
    if not _check_to(tournament_url):
        return jsonify({"error": "Forbidden"}), 403

    recompute_all_match_times(tournament_url)
    return jsonify({"success": True})


@bp.route("/tournaments/<tournament_url>/update-all-references", methods=["POST"])
@login_required
def update_all_references_api(tournament_url):
    if not _check_to(tournament_url):
        return jsonify({"error": "Forbidden"}), 403

    completed = (
        Match.query.filter_by(event=tournament_url)
        .filter(Match.status.in_([MatchStatus.COMPLETED, MatchStatus.SKIPPED]))
        .all()
    )
    for m in completed:
        apply_match_dependencies(tournament_url, m)

    return jsonify({"success": True})


@bp.route("/tournaments/<tournament_url>/push-back-matches", methods=["POST"])
@login_required
def push_back_matches_api(tournament_url):
    if not _check_to(tournament_url):
        return jsonify({"error": "Forbidden"}), 403

    data = request.get_json()
    minutes = int(data.get("minutes", 0))
    if not minutes:
        return jsonify({"success": True})

    matches = (
        Match.query.filter_by(event=tournament_url)
        .filter(Match.status.in_([MatchStatus.NOT_STARTED, MatchStatus.TIME_FINALIZED]))
        .all()
    )
    from datetime import timedelta

    for m in matches:
        if m.schedule_type == ScheduleType.STATIC and m.nominal_start_time:
            m.nominal_start_time += timedelta(minutes=minutes)

    db.session.commit()
    recompute_all_match_times(tournament_url)
    return jsonify({"success": True})


@bp.route("/tournaments/<tournament_url>/update-tags", methods=["POST"])
@login_required
def update_tags_api(tournament_url):
    if not _check_to(tournament_url):
        return jsonify({"error": "Forbidden"}), 403

    data = request.get_json()
    tag_id = data.get("tag_id")
    team_id = data.get("team_id")

    if not tag_id:
        return jsonify({"error": "Tag required"}), 400

    tag = Tag.query.filter_by(id=tag_id, event=tournament_url).first_or_404()
    tag.team = team_id if team_id else None
    db.session.commit()

    # Update matches
    matches = Match.query.filter_by(event=tournament_url).all()
    tag_ref = f"tag::{tag.name}"

    for m in matches:
        if m.status in (
            MatchStatus.COMPLETED,
            MatchStatus.SKIPPED,
            MatchStatus.IN_PROGRESS,
        ):
            continue
        if m.team1_initial == tag_ref:
            m.team1 = team_id
        if m.team2_initial == tag_ref:
            m.team2 = team_id

        for row in get_match_referee_rows(m):
            if (row.initial or "").strip() == tag_ref:
                row.team_id = team_id

    db.session.commit()
    recompute_all_match_times(tournament_url)
    return jsonify({"success": True})


@bp.route("/tournaments/<tournament_url>/export-schedule", methods=["GET"])
@login_required
def export_schedule_api(tournament_url):
    if not _check_to(tournament_url):
        return jsonify({"error": "Forbidden"}), 403

    from app.services.schedule_import_export_service import ScheduleImportExportService
    from app.utils.result_helpers import json_from_result

    res = ScheduleImportExportService.export_schedule(tournament_url)
    return json_from_result(res, ok_to_payload=lambda v: {"toml": v})


@bp.route("/tournaments/<tournament_url>/import-schedule", methods=["POST"])
@login_required
def import_schedule_api(tournament_url):
    if not _check_to(tournament_url):
        return jsonify({"error": "Forbidden"}), 403

    data = request.get_json()
    toml_content = data.get("toml")
    if not toml_content:
        return jsonify({"error": "TOML content required"}), 400

    from app.services.schedule_import_export_service import ScheduleImportExportService
    from app.utils.result_helpers import json_from_result

    def _ok_payload(_):
        recompute_all_match_times(tournament_url)
        return {}

    res = ScheduleImportExportService.import_schedule(tournament_url, toml_content)
    return json_from_result(res, ok_to_payload=_ok_payload)
