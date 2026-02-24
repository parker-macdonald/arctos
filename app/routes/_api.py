"""
Internal JSON API for the Dioxus SPA. All routes live under /_api/.
Do not use /api/ — that is reserved for a future public API.
"""

from flask import Blueprint, request, jsonify, session, redirect, current_app
from datetime import datetime, timezone
from pathlib import Path
import os
from flask_login import current_user, login_user, logout_user, login_required
from sqlalchemy import or_, func
from sqlalchemy.orm import joinedload
from app.services.tournament_service import TournamentService
from app.utils.helpers import (
    is_valid_url_username,
    check_tournament_access,
    can_head_ref_match,
    resolve_team_name_to_id,
    DEFAULT_PENALTY_COLORS,
    get_next_penalty_color,
)
from app.utils.dependencies import apply_match_dependencies
from app.serializers.match_note_serializer import MatchNoteSerializer
from app.error_values import Ok, Err
from app.routes.tournaments import update_match_previous_link
from app.utils.scheduling import (
    recompute_all_match_times,
    compute_dynamic_match_nominal_start_time,
)
from app.utils.datetime_helpers import to_iso_z
from app.domain.enums import RegistrationStatus, MatchStatus, ScheduleType, SetType
from models import (
    Player,
    Team,
    Tournament,
    Match,
    Point,
    Field,
    Tag,
    Injury,
    MatchNote,
    TeamRegistration,
    PlayerRegistration,
    TO,
    PenaltyType,
    db,
)
import json

bp = Blueprint("_api", __name__, url_prefix="/_api")


@bp.route("/")
def login_redirect():
    """Redirect to SPA root (used as login_view when unauthenticated)."""
    return redirect("/")


def _dt_iso(dt):
    if dt is None:
        return None
    if hasattr(dt, "isoformat"):
        return dt.isoformat()
    return str(dt)


def _user_json():
    if not current_user.is_authenticated:
        return None
    t = "player" if current_user.__class__.__name__ == "Player" else "team"
    return {"id": current_user.id, "name": current_user.name, "type": t}


@bp.route("/me", methods=["GET"])
def me():
    """Return current user or 401."""
    u = _user_json()
    if u is None:
        return jsonify({"error": "Not authenticated"}), 401
    return jsonify(u)


@bp.route("/server-time", methods=["GET"])
def server_time():
    """Return current server time in unix timestamp format."""
    import time

    return jsonify(
        {
            "server_time": time.time(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )


@bp.route("/login", methods=["POST"])
def login():
    """JSON body: { username, password }. Sets session cookie on success."""
    if not request.is_json:
        return jsonify({"error": "Content-Type must be application/json"}), 415
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400
    username = data.get("username")
    password = data.get("password")
    if not username or not password:
        return jsonify({"error": "username and password required"}), 400
    user = Player.query.filter_by(id=username).first()
    if not user:
        user = Team.query.filter_by(id=username).first()
    if not user or not user.check_password(password):
        return jsonify({"error": "Invalid username or password"}), 401
    login_user(user)
    return jsonify(_user_json())


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    """Clear session."""
    logout_user()
    return jsonify({"ok": True})


@bp.route("/register", methods=["POST"])
def register():
    """JSON body: { username, password, name, user_type?: "player"|"team" }. Creates user and logs in."""
    if not request.is_json:
        return jsonify({"error": "Content-Type must be application/json"}), 415
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400
    username = data.get("username")
    password = data.get("password")
    name = data.get("name")
    user_type = data.get("user_type", "player")
    if not username or not password or not name:
        return jsonify({"error": "username, password, and name required"}), 400
    if user_type not in ("player", "team"):
        return jsonify({"error": "user_type must be player or team"}), 400
    if not is_valid_url_username(username):
        return (
            jsonify(
                {
                    "error": "Username must be URL-safe: letters, numbers, hyphens, underscores. Cannot start or end with hyphen or underscore.",
                }
            ),
            400,
        )
    if (
        Player.query.filter_by(id=username).first()
        or Team.query.filter_by(id=username).first()
    ):
        return jsonify({"error": "Username already exists"}), 409
    if user_type == "player":
        user = Player(id=username, name=name)
    else:
        user = Team(id=username, name=name)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    login_user(user)
    return jsonify(_user_json())


@bp.route("/check-username", methods=["GET"])
def check_username():
    """Query param: username. Returns { available: bool, message: str }."""
    username = request.args.get("username", "").strip()
    if not username:
        return jsonify({"available": False, "message": "Username is required"})
    if not is_valid_url_username(username):
        return jsonify(
            {
                "available": False,
                "message": "Username must be URL-safe: letters, numbers, hyphens, underscores. Cannot start or end with hyphen or underscore.",
            }
        )
    if (
        Player.query.filter_by(id=username).first()
        or Team.query.filter_by(id=username).first()
    ):
        return jsonify({"available": False, "message": "Username already exists"})
    return jsonify({"available": True, "message": "Username is available"})


@bp.route("/google/choose-account-type", methods=["GET", "POST"])
def google_choose_account_type_api():
    oauth_data = session.get("google_oauth_data")
    if not oauth_data:
        return jsonify({"error": "Session expired"}), 401

    if request.method == "POST":
        if not request.is_json:
            return jsonify({"error": "Content-Type must be application/json"}), 415
        data = request.get_json()
        if not data:
            return jsonify({"error": "Invalid JSON"}), 400
        user_type = data.get("user_type")
        if user_type not in ["player", "team"]:
            return jsonify({"error": "Please select an account type"}), 400
        oauth_data["user_type"] = user_type
        session["google_oauth_data"] = oauth_data
        session.modified = True
        return jsonify({"ok": True})

    return jsonify({"email": oauth_data.get("email", "")})


@bp.route("/google/complete-profile", methods=["GET", "POST"])
def google_complete_profile_api():
    oauth_data = session.get("google_oauth_data")
    if not oauth_data:
        return jsonify({"error": "Session expired"}), 401

    user_type = oauth_data.get("user_type")
    if not user_type:
        return jsonify({"error": "Account type not selected"}), 400

    email = oauth_data.get("email", "")
    suggested_name = oauth_data.get("name", email.split("@")[0] if email else "User")

    if request.method == "POST":
        if not request.is_json:
            return jsonify({"error": "Content-Type must be application/json"}), 415
        data = request.get_json()
        if not data:
            return jsonify({"error": "Invalid JSON"}), 400
        username = (data.get("username") or "").strip()
        display_name = (data.get("display_name") or "").strip()

        if not username:
            return jsonify({"error": "Username is required"}), 400
        if not is_valid_url_username(username):
            return (
                jsonify(
                    {
                        "error": "Username must be URL-safe: only letters, numbers, hyphens, and underscores. Cannot start or end with hyphen or underscore.",
                    }
                ),
                400,
            )
        existing_player = Player.query.filter_by(id=username).first()
        existing_team = Team.query.filter_by(id=username).first()
        if existing_player or existing_team:
            return jsonify({"error": "Username already exists"}), 409
        if not display_name:
            return jsonify({"error": "Display name is required"}), 400

        if user_type == "player":
            user = Player(
                id=username,
                name=display_name,
                google_id=oauth_data["google_id"],
                email=email,
                profile_photo=(
                    None if username.lower() not in ("jeb", "jebediah") else "jeb.png"
                ),
            )
        else:
            user = Team(
                id=username,
                name=display_name,
                google_id=oauth_data["google_id"],
                email=email,
                profile_photo=(
                    None if username.lower() not in ("jeb", "jebediah") else "jeb.png"
                ),
            )
        db.session.add(user)
        db.session.commit()
        session.pop("google_oauth_data", None)
        login_user(user)
        return jsonify({"ok": True})

    return jsonify(
        {
            "email": email,
            "user_type": user_type,
            "suggested_name": suggested_name,
        }
    )


def _tournament_to_dict(t):
    end = t.end_date.isoformat() if t.end_date else None
    start = t.start_date.isoformat() if t.start_date else None
    return {
        "url": t.url,
        "name": t.name,
        "start_date": start,
        "end_date": end,
        "location": t.location,
        "published": t.published,
        "n_max_teams": t.n_max_teams,
        "schedule_published": getattr(t, "schedule_published", False),
        "registration_open": getattr(t, "registration_open", False),
        "bracket": bool(getattr(t, "bracket", None)),
        "about": getattr(t, "about", None),
        "team_reg_fee": getattr(t, "team_reg_fee", None),
        "player_reg_fee": getattr(t, "player_reg_fee", None),
        "num_fields": getattr(t, "num_fields", None),
        "max_team_size_roster": getattr(t, "max_team_size_roster", None),
        "max_team_size_field": getattr(t, "max_team_size_field", None),
        "terms_link": getattr(t, "terms_link", None),
        "head_refs_allowed_list": getattr(t, "head_refs_allowed_list", None),
        "head_refs_allow_reffing_teams": bool(
            getattr(t, "head_refs_allow_reffing_teams", False)
        ),
        "head_refs_allow_anyone": bool(getattr(t, "head_refs_allow_anyone", False)),
    }


@bp.route("/tournaments", methods=["GET"])
def tournaments():
    """List tournaments (same visibility as homepage). Returns { upcoming, past, team_counts, user_reg_status }."""
    ctx = TournamentService.get_homepage_context(current_user)
    team_counts = ctx["team_counts"]
    user_reg_status = ctx["user_reg_status"]
    upcoming = [_tournament_to_dict(t) for t in ctx["upcoming_tournaments"]]
    past = [_tournament_to_dict(t) for t in ctx["past_tournaments"]]
    return jsonify(
        {
            "upcoming": upcoming,
            "past": past,
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
    tournament, err = _require_tournament(tournament_url)
    if err:
        return jsonify({"error": "Not found"}), err
    team_regs = TeamRegistration.query.filter_by(
        event=tournament_url, status=RegistrationStatus.CONFIRMED
    ).all()
    teams_with_counts = []
    for team_reg in team_regs:
        n = PlayerRegistration.query.filter_by(
            event=tournament_url,
            team=team_reg.team,
            status=RegistrationStatus.CONFIRMED,
        ).count()
        team = Team.query.get(team_reg.team)
        teams_with_counts.append(
            {
                "team_id": team_reg.team,
                "team_name": team.name if team else team_reg.team,
                "pseudonym": team_reg.pseudonym,
                "player_count": n,
                "registered_at": _dt_iso(getattr(team_reg, "registered_at", None)),
                "profile_photo": team.profile_photo if team else None,
            }
        )
    unattached = []
    for pr in PlayerRegistration.query.filter_by(
        event=tournament_url, team=None, status=RegistrationStatus.CONFIRMED
    ).all():
        p = Player.query.get(pr.player)
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
    to_rows = TO.query.filter_by(event=tournament_url).all()
    to_entries = []
    for e in to_rows:
        if e.user_type == "player":
            user = Player.query.get(e.user_id)
            user_name = user.name if user else e.user_id
        else:
            user = Team.query.get(e.user_id)
            user_name = user.name if user else e.user_id
        is_current = (
            current_user.is_authenticated
            and current_user.id == e.user_id
            and current_user.__class__.__name__.lower() == e.user_type
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
        if current_user.__class__.__name__ == "Team":
            is_current_team_registered = (
                TeamRegistration.query.filter_by(
                    event=tournament_url,
                    team=current_user.id,
                    status=RegistrationStatus.CONFIRMED,
                ).first()
                is not None
            )
        else:
            is_current_player_registered = (
                PlayerRegistration.query.filter_by(
                    event=tournament_url, player=current_user.id
                )
                .filter(
                    PlayerRegistration.status.in_(
                        [
                            RegistrationStatus.PENDING_TEAM_APPROVAL,
                            RegistrationStatus.CONFIRMED,
                        ]
                    )
                )
                .first()
                is not None
            )
    
    penalty_types = PenaltyType.query.filter_by(event=tournament_url).all()
    penalty_types_data = [
        {"id": t.id, "name": t.name, "color": t.color, "desc": (t.desc or "")}
        for t in penalty_types
    ]

    return jsonify(
        {
            "tournament": _tournament_to_dict(tournament),
            "teams_with_counts": teams_with_counts,
            "unattached_players": unattached,
            "to_entries": to_entries,
            "is_current_team_registered": is_current_team_registered,
            "is_current_player_registered": is_current_player_registered,
            "penalty_types": penalty_types_data,
        }
    )


@bp.route("/tournaments/<tournament_url>/manage", methods=["GET"])
@login_required
def tournament_manage_api(tournament_url):
    if not _check_to(tournament_url):
        return jsonify({"error": "Forbidden"}), 403

    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()
    search_query = (request.args.get("search") or "").strip()
    search_type = (request.args.get("type") or "both").lower()

    team_registrations = (
        TeamRegistration.query.filter_by(event=tournament_url)
        .filter(TeamRegistration.status != RegistrationStatus.CANCELLED)
        .all()
    )
    teams_with_registrations = []
    for team_reg in team_registrations:
        team = Team.query.get(team_reg.team)
        if team:
            teams_with_registrations.append({"registration": team_reg, "team": team})

    player_registrations = (
        PlayerRegistration.query.filter_by(event=tournament_url)
        .filter(PlayerRegistration.status != RegistrationStatus.CANCELLED)
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

    return jsonify(
        {
            "tournament": _tournament_to_dict(tournament),
            "search_query": search_query,
            "search_type": search_type,
            "team_registrations": [
                {
                    "registration": {
                        "id": tr["registration"].id,
                        "team": tr["registration"].team,
                        "pseudonym": tr["registration"].pseudonym,
                        "status": (
                            tr["registration"].status.value
                            if hasattr(tr["registration"].status, "value")
                            else str(tr["registration"].status)
                        ),
                        "paid": bool(tr["registration"].paid),
                        "amount_paid": tr["registration"].amount_paid or 0.0,
                        "registered_at": _dt_iso(tr["registration"].registered_at),
                        "paid_at": _dt_iso(tr["registration"].paid_at),
                    },
                    "team": {
                        "id": tr["team"].id,
                        "name": tr["team"].name,
                    },
                }
                for tr in teams_with_registrations
            ],
            "player_registrations": [
                {
                    "registration": {
                        "id": pr["registration"].id,
                        "player": pr["registration"].player,
                        "team": pr["registration"].team,
                        "jersey_name": pr["registration"].jersey_name,
                        "jersey_number": pr["registration"].jersey_number,
                        "status": (
                            pr["registration"].status.value
                            if hasattr(pr["registration"].status, "value")
                            else str(pr["registration"].status)
                        ),
                        "paid": bool(pr["registration"].paid),
                        "amount_paid": pr["registration"].amount_paid or 0.0,
                        "registered_at": _dt_iso(pr["registration"].registered_at),
                        "paid_at": _dt_iso(pr["registration"].paid_at),
                    },
                    "player": {
                        "id": pr["player"].id,
                        "name": pr["player"].name,
                    },
                    "team": (
                        {
                            "id": pr["team"].id,
                            "name": pr["team"].name,
                        }
                        if pr["team"]
                        else None
                    ),
                }
                for pr in players_with_registrations
            ],
        }
    )


@bp.route("/tournaments/<tournament_url>/invitations", methods=["GET"])
@login_required
def tournament_invitations_api(tournament_url):
    if current_user.__class__.__name__ != "Team":
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

    all_player_registrations = PlayerRegistration.query.filter_by(
        event=tournament_url, team=current_user.id
    ).all()
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
def tournament_bracket_setup_save_api(tournament_url):
    """Save bracket configuration from the SPA."""
    if not _check_to(tournament_url):
        return jsonify({"error": "Forbidden"}), 403

    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()

    if not request.is_json:
        return jsonify({"error": "Content-Type must be application/json"}), 415

    data = request.get_json(silent=True) or {}
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

    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()

    from flask import current_app
    import os
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
        is_to = (
            TO.query.filter_by(
                user_id=current_user.id,
                user_type=current_user.__class__.__name__.lower(),
                event=tournament_url,
            ).first()
            is not None
        )

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
                    tag = Tag.query.filter_by(
                        event=tournament_url, name=tag_name
                    ).first()
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
                match = Match.query.filter_by(
                    event=tournament_url, name=match_name
                ).first()
                if (
                    match
                    and match.status == MatchStatus.COMPLETED
                    and match.match_winner
                ):
                    if ref_type == "winner":
                        team_id = (
                            match.team1
                            if match.match_winner == "TEAM1"
                            else match.team2
                        )
                    elif ref_type == "loser":
                        team_id = (
                            match.team2
                            if match.match_winner == "TEAM1"
                            else match.team1
                        )
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
                        "profile_photo": team.profile_photo if team else None,
                        "display_text": team_reg.pseudonym,
                    }
                else:
                    tag = Tag.query.filter_by(
                        event=tournament_url, name=team_ref
                    ).first()
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

        processed_brackets.append(
            {"name": bracket_name, "image": bracket_image, "teams": processed_teams}
        )

    return jsonify(
        {"tournament": _tournament_to_dict(tournament), "brackets": processed_brackets}
    )


@bp.route("/tournaments/<tournament_url>/start-match", methods=["GET"])
@login_required
def start_match_data_api(tournament_url):
    match_id = request.args.get("match_id")
    if not match_id:
        return jsonify({"error": "Match ID required"}), 400

    match = Match.query.get(match_id)
    if not match or match.event != tournament_url:
        return jsonify({"error": "Match not found"}), 404

    if not can_head_ref_match(tournament_url, current_user.id, match=match):
        return jsonify({"error": "Forbidden"}), 403

    tournament = Tournament.query.get(tournament_url)

    team1_players = (
        db.session.query(PlayerRegistration, Player)
        .join(Player, PlayerRegistration.player == Player.id)
        .filter(
            PlayerRegistration.event == tournament_url,
            PlayerRegistration.team == match.team1,
            PlayerRegistration.status == RegistrationStatus.CONFIRMED,
        )
        .all()
    )
    team2_players = (
        db.session.query(PlayerRegistration, Player)
        .join(Player, PlayerRegistration.player == Player.id)
        .filter(
            PlayerRegistration.event == tournament_url,
            PlayerRegistration.team == match.team2,
            PlayerRegistration.status == RegistrationStatus.CONFIRMED,
        )
        .all()
    )
    all_players = (
        db.session.query(PlayerRegistration, Player)
        .join(Player, PlayerRegistration.player == Player.id)
        .filter(
            PlayerRegistration.event == tournament_url,
            PlayerRegistration.status == RegistrationStatus.CONFIRMED,
        )
        .all()
    )

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
                "refs": match.refs,
                "team1_name": _team_name_for_match(tournament_url, match, "team1"),
                "team2_name": _team_name_for_match(tournament_url, match, "team2"),
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
    match res:
        case Ok(match_obj):
            return jsonify({"match_id": match_obj.uuid})
        case Err(err):
            return jsonify({"error": str(err)}), 400


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
                "team1_name": _team_name_for_match(tournament_url, match, "team1"),
                "team2_name": _team_name_for_match(tournament_url, match, "team2"),
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

    match.completed_time = datetime.now(timezone.utc).replace(tzinfo=None)
    match.finalized_by = current_user.id
    match.final_notes = data.get("final_notes") or ""
    match.match_winner = match_winner
    match.finalized_at = datetime.now(timezone.utc).replace(tzinfo=None)

    if match.field:
        field_obj = Field.query.filter_by(
            event=tournament_url, name=match.field
        ).first()
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
    if TO.query.filter_by(
        user_id=current_user.id,
        user_type=current_user.__class__.__name__.lower(),
        event=tournament_url,
    ).first():
        return True
    if current_user.__class__.__name__ == "Player" and can_head_ref_match(
        tournament_url, current_user.id, match=None
    ):
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
    matches = (
        Match.query.filter_by(event=tournament_url)
        .order_by(Match.nominal_start_time)
        .all()
    )
    fields = [
        {"id": f.id, "name": f.name}
        for f in Field.query.filter_by(event=tournament_url).order_by(Field.name).all()
    ]
    team_options = []
    seen = set()
    for tr in TeamRegistration.query.filter_by(
        event=tournament_url, status=RegistrationStatus.CONFIRMED
    ).all():
        if tr.team not in seen:
            team = Team.query.get(tr.team)
            team_options.append(
                {
                    "id": tr.team,
                    "pseudonym": tr.pseudonym,
                    "profile_photo": team.profile_photo if team else None,
                }
            )
            seen.add(tr.team)
    for m in matches:
        for initial, key in [(m.team1_initial, "team1"), (m.team2_initial, "team2")]:
            if not initial or initial in seen:
                continue
            if (
                "::winner" in initial
                or "::loser" in initial
                or " winner" in initial
                or " loser" in initial
            ):
                continue
            team_options.append(
                {"id": initial, "pseudonym": initial, "profile_photo": None}
            )
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
                "status": (
                    m.status.value if hasattr(m.status, "value") else str(m.status)
                ),
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


def _team_pseudonym_and_photo(tournament_url, team_id):
    """Return (pseudonym, profile_photo) for a team in an event."""
    if not team_id:
        return None, None
    reg = TeamRegistration.query.filter_by(event=tournament_url, team=team_id).first()
    pseudonym = reg.pseudonym if reg and reg.pseudonym else None
    team = Team.query.get(team_id)
    profile_photo = team.profile_photo if team else None
    if not pseudonym and team:
        pseudonym = team.name
    if not pseudonym:
        pseudonym = team_id
    return pseudonym, profile_photo


@bp.route("/tournaments/<tournament_url>/results", methods=["GET"])
def tournament_results(tournament_url):
    """Tournament results: teams with aggregate stats (no per-match data)."""
    tournament, err = _require_tournament(tournament_url)
    if err:
        return jsonify({"error": "Not found"}), err
    matches = Match.query.filter(
        Match.event == tournament_url,
        Match.status.in_([MatchStatus.COMPLETED, MatchStatus.SKIPPED]),
    ).all()
    include_ribbon = request.args.get("include_ribbon", "").lower() in ("1", "true", "yes")
    # Exclude BREAK/JOIN; exclude ribbon games from stats unless include_ribbon=True
    count_matches = [
        m
        for m in matches
        if getattr(m, "schedule_type", None)
        not in (ScheduleType.BREAK, ScheduleType.JOIN)
        and (include_ribbon or not getattr(m, "ribbon", False))
    ]
    points_by_match = {}
    if count_matches:
        match_ids = [m.uuid for m in count_matches]
        for p in Point.query.filter(Point.match.in_(match_ids)).all():
            points_by_match.setdefault(p.match, []).append(p)
    team_stats = {}
    for m in count_matches:
        t1 = m.team1 or m.team1_initial
        t2 = m.team2 or m.team2_initial
        for tid, is_team1 in [(t1, True), (t2, False)]:
            if not tid or tid == "TBA" or "::" in str(tid):
                continue
            if tid not in team_stats:
                if str(tid).startswith("tag::") or "::" in str(tid):
                    pseudonym, profile_photo = tid, None
                else:
                    pseudonym, profile_photo = _team_pseudonym_and_photo(
                        tournament_url, tid
                    )
                team_stats[tid] = {
                    "id": tid,
                    "pseudonym": pseudonym or tid,
                    "profile_photo": profile_photo,
                    "matches_won": 0,
                    "matches_lost": 0,
                    "points_won": 0,
                    "points_lost": 0,
                }
        winner = m.match_winner.value if m.match_winner else None
        if winner and t1 and t2 and t1 != "TBA" and t2 != "TBA":
            if winner == "TEAM1":
                team_stats[t1]["matches_won"] += 1
                team_stats[t2]["matches_lost"] += 1
            elif winner == "TEAM2":
                team_stats[t2]["matches_won"] += 1
                team_stats[t1]["matches_lost"] += 1
        points_list = points_by_match.get(m.uuid, [])
        t1p = sum(
            1
            for p in points_list
            if getattr(p, "winner", None) == "TEAM1"
            and not getattr(p, "rerolled", False)
        )
        t2p = sum(
            1
            for p in points_list
            if getattr(p, "winner", None) == "TEAM2"
            and not getattr(p, "rerolled", False)
        )
        if t1 and t1 != "TBA":
            team_stats[t1]["points_won"] += t1p
            team_stats[t1]["points_lost"] += t2p
        if t2 and t2 != "TBA":
            team_stats[t2]["points_won"] += t2p
            team_stats[t2]["points_lost"] += t1p
    teams_list = list(team_stats.values())
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
        team1_name = _team_name_for_match(tournament_url, m, "team1")
        team2_name = _team_name_for_match(tournament_url, m, "team2")
        points_list = points_by_match.get(m.uuid, [])
        set_scores = {}
        for p in points_list:
            if getattr(p, "rerolled", False):
                continue
            sn = getattr(p, "set_number", None) or 1
            set_scores.setdefault(
                sn, {"set_number": sn, "team1_points": 0, "team2_points": 0}
            )
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
    return jsonify(
        {"fields": [{"id": f.id, "name": f.name, "camera": f.camera} for f in fields]}
    )


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
    fields_query = (
        Field.query.filter_by(event=tournament_url).order_by(Field.name).all()
    )
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
    matches_query = (
        Match.query.filter_by(event=tournament_url)
        .order_by(Match.nominal_start_time)
        .all()
    )
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
                "status": (
                    m.status.value if hasattr(m.status, "value") else str(m.status)
                ),
                "nominal_start_time": _dt_iso(m.nominal_start_time),
                "confirmed_start_time": _dt_iso(m.confirmed_start_time),
                "completed_time": _dt_iso(m.completed_time),
                "schedule_type": m.schedule_type.value if m.schedule_type else None,
                "set_type": m.set_type.value if m.set_type else None,
                "nominal_length": m.nominal_length,
                "previous_match": m.previous_match,
                "next_match": m.next_match,
                "refs": m.refs,
                "refs_initial": m.refs_initial,
                "ribbon": m.ribbon,
                "skip_condition": m.skip_condition,
                "nsets": m.nsets,
                "stones_per_set": m.stones_per_set or m.nstonesperset,
                "stones_remaining": m.stones_remaining,
                "match_winner": m.match_winner.value if m.match_winner else None,
            }
        )

    # Team Options: only teams with valid (confirmed) registration for this tournament.
    # Create/edit match modals use this; match refs (MatchName::winner/loser) and tags (tag::Name) are offered separately.
    team_options = []
    seen = set()
    for tr in TeamRegistration.query.filter_by(
        event=tournament_url, status=RegistrationStatus.CONFIRMED
    ).all():
        if tr.team not in seen:
            team = Team.query.get(tr.team)
            team_options.append(
                {
                    "id": tr.team,
                    "pseudonym": tr.pseudonym,
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


def _team_name_for_match(tournament_url, match, team_key):
    team_id = getattr(match, team_key)
    if not team_id:
        initial = getattr(match, f"{team_key}_initial", None)
        return initial or f"Team {team_key[-1]}"
    reg = TeamRegistration.query.filter_by(event=tournament_url, team=team_id).first()
    if reg and reg.pseudonym:
        return reg.pseudonym
    t = Team.query.get(team_id)
    return t.name if t else team_id


def _team_display_name(tournament_url, team_id):
    """Resolve a team id to display name (pseudonym preferred, else team name)."""
    if not team_id or not str(team_id).strip():
        return None
    reg = TeamRegistration.query.filter_by(event=tournament_url, team=team_id).first()
    if reg and reg.pseudonym:
        return reg.pseudonym
    t = Team.query.get(team_id)
    return t.name if t else team_id


def _refs_display_for_match(tournament_url, match):
    """Refs as comma-separated display names (pseudonym for each ref team), like team1_name/team2_name."""
    if not match.refs:
        return match.refs_initial
    parts = []
    for tid in (match.refs or "").split(","):
        tid = tid.strip()
        if not tid:
            continue
        name = _team_display_name(tournament_url, tid)
        if name:
            parts.append(name)
    return ",".join(parts) if parts else match.refs_initial


@bp.route("/tournaments/<tournament_url>/match", methods=["GET"])
def tournament_match_detail(tournament_url):
    """Match detail by id= or name=. Returns match metadata and points."""
    tournament, err = _require_tournament(tournament_url)
    if err:
        return jsonify({"error": "Not found"}), err
    match_id = request.args.get("id", "").strip()
    match_name = request.args.get("name", "").strip()
    if not match_id and not match_name:
        return jsonify({"error": "Match id or name required"}), 400
    if match_id:
        match = Match.query.filter_by(uuid=match_id, event=tournament_url).first()
    else:
        match = Match.query.filter_by(name=match_name, event=tournament_url).first()
    if not match:
        return jsonify({"error": "Match not found"}), 404
    points = Point.query.filter_by(match=match.uuid).order_by(Point.stamp).all()
    team1_name = _team_name_for_match(tournament_url, match, "team1")
    team2_name = _team_name_for_match(tournament_url, match, "team2")
    points_data = [
        {
            "uuid": p.uuid,
            "set_number": p.set_number,
            "winner": p.winner,
            "rerolled": p.rerolled,
            "stamp": _dt_iso(p.stamp),
            "end_stamp": _dt_iso(p.end_stamp),
            "stones_at_start": (
                p.stones_at_start if match.set_type == SetType.STONES else None
            ),
        }
        for p in points
    ]

    # Get camera data (same logic as match_page route)
    available_cameras = []
    camera_url = None
    from app.utils.camera_helpers import parse_camera_urls
    import os
    from flask import current_app

    stream_starts = {}
    recorded_videos = []
    camera_urls = []

    if match.camera_stream_starts:
        try:
            stream_starts_data = json.loads(match.camera_stream_starts)
            for camera_id, recording_data in stream_starts_data.items():
                recordings = (
                    recording_data
                    if isinstance(recording_data, list)
                    else [recording_data]
                )
                for recording in recordings:
                    if isinstance(recording, dict) and "video_path" in recording:
                        video_path = recording.get("video_path", "")
                        if video_path:
                            if video_path.startswith("static/"):
                                video_full_path = os.path.join(
                                    current_app.root_path, "..", video_path
                                )
                            else:
                                video_full_path = os.path.join(
                                    current_app.root_path, "../static", video_path
                                )
                            if os.path.exists(video_full_path):
                                recorded_videos.append(
                                    {
                                        "camera_id": camera_id,
                                        "video_path": video_path,
                                        "point_timestamps": recording.get(
                                            "point_timestamps"
                                        ),
                                        "type": "recorded",
                                        "start_time": recording.get("start_time"),
                                        "start_timestamp": recording.get(
                                            "start_timestamp"
                                        ),
                                        "session_id": recording.get("session_id"),
                                    }
                                )
        except (json.JSONDecodeError, TypeError):
            pass

    # Get YouTube cameras from field configuration
    if match.field:
        field_obj = Field.query.filter_by(
            event=tournament_url, name=match.field
        ).first()
        if field_obj and field_obj.camera:
            camera_urls = parse_camera_urls(field_obj.camera)
            if camera_urls:
                for idx, url in enumerate(camera_urls):
                    stream_start_str = stream_starts.get(str(idx))
                    available_cameras.append(
                        {
                            "index": idx,
                            "url": url,
                            "stream_start_time": (
                                stream_start_str if stream_start_str else None
                            ),
                            "type": "youtube",
                        }
                    )

    # Add recorded videos whenever we have them (match may be in progress, completed, or not yet started)
    if recorded_videos:
        for idx, recording in enumerate(recorded_videos):
            start_time = recording.get("start_time")
            if not start_time and recording.get("start_timestamp"):
                start_time = datetime.fromtimestamp(
                    int(recording["start_timestamp"]) / 1000, tz=timezone.utc
                ).isoformat()
            available_cameras.append(
                {
                    "index": len(camera_urls) + idx,
                    "url": None,
                    "stream_start_time": start_time,
                    "type": "recorded",
                    "video_path": recording["video_path"],
                    "camera_id": recording.get("camera_id", "unknown"),
                    "session_id": recording.get("session_id", ""),
                    "point_timestamps": recording.get("point_timestamps"),
                }
            )

    if available_cameras:
        first_cam = available_cameras[0]
        if first_cam.get("type") == "youtube":
            camera_url = first_cam["url"]

    # Get match notes
    initial_notes = match.initial_notes or ""
    final_notes = match.final_notes or ""
    match_notes = []
    point_notes_map = {}

    # Check if user is head ref
    is_head_ref = False
    if current_user.is_authenticated:
        from app.utils.user_helpers import is_player

        if is_player(current_user):
            is_head_ref = can_head_ref_match(
                tournament_url, current_user.id, match=match
            )

    # Get match-level notes (point_id is None) - only for head refs
    if is_head_ref:
        notes = (
            MatchNote.query.filter_by(match=match.uuid, point_id=None)
            .order_by(MatchNote.created_at.desc())
            .all()
        )
        from app.utils.player_helpers import get_player_display_name

        for note in notes:
            player_name = None
            player_display = None
            if note.player_id:
                player_name, player_display = get_player_display_name(
                    note.player_id, tournament_url
                )
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
    team1_selected = set()
    if match.team1_players:
        try:
            team1_selected = set(json.loads(match.team1_players))
        except:
            pass

    team2_selected = set()
    if match.team2_players:
        try:
            team2_selected = set(json.loads(match.team2_players))
        except:
            pass

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
            pr = (
                PlayerRegistration.query.filter_by(
                    event=tournament_url,
                    player=pid,
                    status=RegistrationStatus.CONFIRMED,
                ).first()
            )
            display = (
                get_player_display_from_registration(player, pr)
                if pr
                else (player.name or pid)
            )
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
            pr = (
                PlayerRegistration.query.filter_by(
                    event=tournament_url,
                    player=pid,
                    status=RegistrationStatus.CONFIRMED,
                ).first()
            )
            display = (
                get_player_display_from_registration(player, pr)
                if pr
                else (player.name or pid)
            )
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
        # Count per player and penalty type
        results = (
            db.session.query(
                MatchNote.player_id,
                MatchNote.penalty_type_id,
                func.count(MatchNote.uuid),
            )
            .join(Match)
            .filter(
                Match.event == tournament_url,
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

    # Get penalty types
    penalty_types = PenaltyType.query.filter_by(event=tournament_url).all()
    penalty_types_data = [
        {"id": t.id, "name": t.name, "color": t.color, "desc": (t.desc or "")}
        for t in penalty_types
    ]

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
                    player_name, player_display = get_player_display_name(
                        n.player_id, tournament_url
                    )
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
                "team1_initial": match.team1_initial,
                "team2_initial": match.team2_initial,
                "status": (
                    match.status.value
                    if hasattr(match.status, "value")
                    else str(match.status)
                ),
                "nominal_start_time": _dt_iso(match.nominal_start_time),
                "confirmed_start_time": _dt_iso(match.confirmed_start_time),
                "completed_time": _dt_iso(match.completed_time),
                "set_type": match.set_type.value if match.set_type else None,
                "stones_per_set": match.stones_per_set or match.nstonesperset,
                "stones_remaining": match.stones_remaining,
                "match_winner": (
                    match.match_winner.value if match.match_winner else None
                ),
                "schedule_type": (
                    match.schedule_type.value if match.schedule_type else None
                ),
                "nominal_length": match.nominal_length,
                "previous_match": match.previous_match,
                "refs": match.refs,
                "refs_initial": match.refs_initial,
                "refs_display": _refs_display_for_match(tournament_url, match),
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
            "team1_score": sum(
                1 for p in set_points if p.winner == "TEAM1" and not p.rerolled
            ),
            "team2_score": sum(
                1 for p in set_points if p.winner == "TEAM2" and not p.rerolled
            ),
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
                "stones_at_start": (
                    p.stones_at_start if match.set_type == SetType.STONES else None
                ),
            }
        )

    finalized_at = None
    if (
        match.status in (MatchStatus.COMPLETED, MatchStatus.SKIPPED)
        and match.finalized_at
    ):
        finalized_at = match.finalized_at.isoformat()

    return jsonify(
        {
            "match_id": match.uuid,
            "status": (
                match.status.value
                if hasattr(match.status, "value")
                else str(match.status)
            ),
            "team1_score": team1_score,
            "team2_score": team2_score,
            "scores_by_set": scores_by_set,
            "points": points_data,
            "stones_remaining": (
                match.stones_remaining
                if getattr(match, "set_type", None) == SetType.STONES
                else None
            ),
            "finalized_at": finalized_at,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )


@bp.route("/players", methods=["GET"])
def players_list():
    """List players with optional search and pagination."""
    search = request.args.get("search", "").strip()
    page = max(1, request.args.get("page", type=int) or 1)
    per_page = 50
    if search:
        q = Player.query.filter(
            Player.name.contains(search) | Player.id.contains(search)
        )
    else:
        q = Player.query
    total = q.count()
    total_pages = (total + per_page - 1) // per_page
    players = (
        q.order_by(Player.name.asc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    return jsonify(
        {
            "players": [
                {
                    "id": p.id,
                    "name": p.name,
                    "profile_photo": p.profile_photo,
                    "location": p.location,
                }
                for p in players
            ],
            "page": page,
            "total_pages": total_pages,
            "total": total,
        }
    )


@bp.route("/players/<player_id>", methods=["GET"])
def player_profile(player_id):
    """Player profile (public)."""
    player = Player.query.get(player_id)
    if not player:
        return jsonify({"error": "Not found"}), 404
    regs = PlayerRegistration.query.filter_by(player=player_id).all()
    can_see_private = current_user.is_authenticated and current_user.id == player_id
    injuries_query = Injury.query.filter_by(player=player_id)
    if not can_see_private:
        injuries_query = injuries_query.filter_by(show=True)
    injuries = injuries_query.order_by(Injury.stamp.desc()).all()
    player_notes = []
    if current_user.is_authenticated:
        try:
            all_player_notes = (
                MatchNote.query.filter_by(player_id=player_id)
                .options(joinedload(MatchNote.penalty_type))
                .order_by(MatchNote.created_at.desc())
                .all()
            )
            for note in all_player_notes:
                can_see_note = False
                if current_user.id == player_id:
                    can_see_note = True
                elif current_user.__class__.__name__ == "Player":
                    match_obj = Match.query.get(note.match) if note.match else None
                    if match_obj and can_head_ref_match(
                        match_obj.event, current_user.id, match=match_obj
                    ):
                        can_see_note = True
                if can_see_note:
                    player_notes.append(note)
        except Exception:
            player_notes = []

    penalty_type_ids = {
        getattr(n, "penalty_type_id", None)
        for n in player_notes
        if getattr(n, "penalty_type_id", None)
    }
    pt_map = {}
    if penalty_type_ids:
        for pt in PenaltyType.query.filter(
            PenaltyType.id.in_(penalty_type_ids)
        ).all():
            pt_map[pt.id] = {"name": pt.name, "color": pt.color, "desc": pt.desc or ""}

    player_note_rows = []
    if player_notes:
        match_to_points = {}
        for note in player_notes:
            idx = "-"
            match_obj = Match.query.get(note.match) if note.match else None
            if match_obj and note.point_id:
                match_id = match_obj.uuid
                if match_id not in match_to_points:
                    pts = (
                        Point.query.filter_by(match=match_id)
                        .order_by(Point.stamp)
                        .all()
                    )
                    match_to_points[match_id] = [p.uuid for p in pts]
                order = match_to_points.get(match_id, [])
                if note.point_id in order:
                    idx = order.index(note.point_id) + 1
            pt_id = getattr(note, "penalty_type_id", None)
            pt_rel = getattr(note, "penalty_type", None)
            if pt_rel is not None:
                pt_info = {"name": pt_rel.name, "color": pt_rel.color, "desc": pt_rel.desc or ""}
            else:
                pt_info = pt_map.get(pt_id) if pt_id else None
            if pt_info is None and pt_id:
                _pt = PenaltyType.query.get(pt_id)
                if _pt:
                    pt_info = {"name": _pt.name, "color": _pt.color, "desc": _pt.desc or ""}
            player_note_rows.append(
                {
                    "created_at": _dt_iso(note.created_at),
                    "text": note.text or "",
                    "point_index": str(idx),
                    "penalty_type_id": pt_id,
                    "penalty_type_name": pt_info["name"] if pt_info else None,
                    "penalty_type_color": pt_info["color"] if pt_info else None,
                    "penalty_type_desc": pt_info.get("desc", "") if pt_info else None,
                    "match": (
                        {
                            "event": match_obj.event if match_obj else None,
                            "uuid": match_obj.uuid if match_obj else None,
                            "name": match_obj.name if match_obj else None,
                        }
                        if match_obj
                        else None
                    ),
                }
            )

    def _team_pseudonym(event, team_id):
        if not team_id:
            return None
        reg = TeamRegistration.query.filter_by(event=event, team=team_id).first()
        return reg.pseudonym if reg else None

    return jsonify(
        {
            "player": {
                "id": player.id,
                "name": player.name,
                "profile_photo": player.profile_photo,
                "phone": (
                    player.phone
                    if (current_user.is_authenticated and current_user.id == player_id)
                    else None
                ),
                "location": player.location,
                "bio": player.bio,
            },
            "registrations": [
                {
                    "event": r.event,
                    "team": r.team,
                    "team_pseudonym": _team_pseudonym(r.event, r.team),
                    "status": (
                        r.status.value if hasattr(r.status, "value") else str(r.status)
                    ),
                    "jersey_name": r.jersey_name,
                    "jersey_number": r.jersey_number,
                }
                for r in regs
            ],
            "injuries": [
                {
                    "id": inj.id,
                    "message": inj.message,
                    "stamp": _dt_iso(inj.stamp),
                    "active": bool(inj.active),
                    "show": bool(inj.show),
                }
                for inj in injuries
            ],
            "player_notes": player_note_rows,
        }
    )


def _injury_json(inj):
    return {
        "id": inj.id,
        "message": inj.message,
        "stamp": _dt_iso(inj.stamp),
        "active": bool(inj.active),
        "show": bool(inj.show),
    }


@bp.route("/players/<player_id>/injuries", methods=["GET", "POST"])
@login_required
def player_injuries(player_id):
    if current_user.id != player_id:
        return jsonify({"error": "Forbidden"}), 403

    if request.method == "GET":
        injuries = (
            Injury.query.filter_by(player=player_id).order_by(Injury.stamp.desc()).all()
        )
        return jsonify([_injury_json(inj) for inj in injuries])

    data = request.get_json() or {}
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"error": "Message is required"}), 400

    injury = Injury(
        player=player_id,
        message=message,
        show=bool(data.get("show", False)),
        active=bool(data.get("active", False)),
    )

    custom_date = data.get("custom_date")
    if custom_date:
        try:
            injury.stamp = datetime.strptime(custom_date, "%Y-%m-%d")
        except ValueError:
            return jsonify({"error": "Invalid date format. Use YYYY-MM-DD."}), 400

    db.session.add(injury)
    db.session.commit()
    return jsonify(_injury_json(injury))


@bp.route(
    "/players/<player_id>/injuries/<int:injury_id>", methods=["GET", "PUT", "DELETE"]
)
@login_required
def player_injury(player_id, injury_id):
    if current_user.id != player_id:
        return jsonify({"error": "Forbidden"}), 403

    injury = Injury.query.filter_by(id=injury_id, player=player_id).first_or_404()

    if request.method == "GET":
        return jsonify(_injury_json(injury))

    if request.method == "DELETE":
        db.session.delete(injury)
        db.session.commit()
        return jsonify({"success": True})

    data = request.get_json() or {}
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"error": "Message is required"}), 400
    injury.message = message

    if "show" in data:
        injury.show = bool(data.get("show"))
    if "active" in data:
        injury.active = bool(data.get("active"))

    if "custom_date" in data:
        custom_date = data.get("custom_date")
        if not custom_date:
            injury.stamp = None
        else:
            try:
                injury.stamp = datetime.strptime(custom_date, "%Y-%m-%d")
            except ValueError:
                return jsonify({"error": "Invalid date format. Use YYYY-MM-DD."}), 400

    db.session.commit()
    return jsonify(_injury_json(injury))


@bp.route("/players/<player_id>/injuries/<int:injury_id>", methods=["GET"])
@login_required
def get_injury(player_id, injury_id):
    if current_user.id != player_id:
        return jsonify({"error": "Forbidden"}), 403
    injury = Injury.query.filter_by(id=injury_id, player=player_id).first_or_404()
    return jsonify(
        {
            "id": injury.id,
            "message": injury.message,
            "stamp": _dt_iso(injury.stamp),
            "active": bool(injury.active),
            "show": bool(injury.show),
        }
    )


@bp.route("/players/<player_id>/injuries", methods=["POST"])
@login_required
def create_injury(player_id):
    if current_user.id != player_id:
        return jsonify({"error": "Forbidden"}), 403
    data = request.get_json() or {}
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"error": "message is required"}), 400

    injury = Injury(
        player=player_id,
        message=message,
        show=bool(data.get("show")),
        active=bool(data.get("active")),
    )

    custom_date = data.get("custom_date")
    if custom_date:
        try:
            injury.stamp = datetime.strptime(custom_date, "%Y-%m-%d")
        except ValueError:
            return jsonify({"error": "Invalid date format. Use YYYY-MM-DD."}), 400
    db.session.add(injury)
    db.session.commit()
    return jsonify(
        {
            "id": injury.id,
            "message": injury.message,
            "stamp": _dt_iso(injury.stamp),
            "active": bool(injury.active),
            "show": bool(injury.show),
        }
    )


@bp.route("/players/<player_id>/injuries/<int:injury_id>", methods=["PUT"])
@login_required
def update_injury(player_id, injury_id):
    if current_user.id != player_id:
        return jsonify({"error": "Forbidden"}), 403
    injury = Injury.query.filter_by(id=injury_id, player=player_id).first_or_404()
    data = request.get_json() or {}
    message = data.get("message")
    if message is not None:
        message = message.strip()
        if not message:
            return jsonify({"error": "message is required"}), 400
        injury.message = message
    if "show" in data:
        injury.show = bool(data.get("show"))
    if "active" in data:
        injury.active = bool(data.get("active"))
    if "custom_date" in data:
        custom_date = data.get("custom_date")
        if custom_date:
            try:
                injury.stamp = datetime.strptime(custom_date, "%Y-%m-%d")
            except ValueError:
                return jsonify({"error": "Invalid date format. Use YYYY-MM-DD."}), 400
        else:
            injury.stamp = None
    db.session.commit()
    return jsonify(
        {
            "id": injury.id,
            "message": injury.message,
            "stamp": _dt_iso(injury.stamp),
            "active": bool(injury.active),
            "show": bool(injury.show),
        }
    )


@bp.route("/players/<player_id>/injuries/<int:injury_id>", methods=["DELETE"])
@login_required
def delete_injury_api(player_id, injury_id):
    if current_user.id != player_id:
        return jsonify({"error": "Forbidden"}), 403
    injury = Injury.query.filter_by(id=injury_id, player=player_id).first_or_404()
    db.session.delete(injury)
    db.session.commit()
    return jsonify({"ok": True})


@bp.route("/teams", methods=["GET"])
def teams_list():
    """List teams with optional search."""
    search = request.args.get("search", "").strip()
    if search:
        teams = Team.query.filter(
            Team.name.contains(search) | Team.id.contains(search)
        ).all()
    else:
        teams = Team.query.all()
    return jsonify(
        {
            "teams": [
                {
                    "id": t.id,
                    "name": t.name,
                    "profile_photo": t.profile_photo,
                    "location": t.location,
                }
                for t in teams
            ]
        }
    )


@bp.route("/teams/<team_id>/players", methods=["GET"])
def team_registration_players(team_id):
    """Players registered for a team in an event (public). Event via query param ?event=."""
    event = request.args.get("event")
    if not event:
        return jsonify({"error": "event required"}), 400
    team = Team.query.get(team_id)
    if not team:
        return jsonify({"error": "Not found"}), 404
    # Ensure the team is registered for this event
    team_reg = TeamRegistration.query.filter_by(
        team=team_id, event=event, status=RegistrationStatus.CONFIRMED
    ).first()
    if not team_reg:
        return jsonify({"error": "Not found"}), 404
    accepted_players = PlayerRegistration.query.filter_by(
        event=event, team=team_id, status=RegistrationStatus.CONFIRMED
    ).all()
    players_with_data = []
    for player_reg in accepted_players:
        player = Player.query.get(player_reg.player)
        players_with_data.append(
            {
                "registration": {
                    "player": player_reg.player,
                    "jersey_name": player_reg.jersey_name,
                    "jersey_number": player_reg.jersey_number,
                },
                "player": (
                    {
                        "id": player.id,
                        "name": player.name,
                        "profile_photo": player.profile_photo,
                    }
                    if player
                    else None
                ),
            }
        )
    return jsonify(players_with_data)


@bp.route("/teams/<team_id>", methods=["GET"])
def team_profile(team_id):
    """Team profile (public)."""
    team = Team.query.get(team_id)
    if not team:
        return jsonify({"error": "Not found"}), 404
    regs = TeamRegistration.query.filter_by(
        team=team_id, status=RegistrationStatus.CONFIRMED
    ).all()
    tournaments = Tournament.query.all()
    tournament_start = {t.url: t.start_date for t in tournaments}

    tournament_players = {}
    if (
        current_user.is_authenticated
        and current_user.id == team_id
        and current_user.__class__.__name__ == "Team"
    ):
        for team_reg in regs:
            accepted_players = PlayerRegistration.query.filter_by(
                event=team_reg.event, team=team_id, status=RegistrationStatus.CONFIRMED
            ).all()
            players_with_data = []
            for player_reg in accepted_players:
                player = Player.query.get(player_reg.player)
                players_with_data.append(
                    {
                        "registration": {
                            "player": player_reg.player,
                            "jersey_name": player_reg.jersey_name,
                            "jersey_number": player_reg.jersey_number,
                        },
                        "player": (
                            {
                                "id": player.id,
                                "name": player.name,
                                "profile_photo": player.profile_photo,
                            }
                            if player
                            else None
                        ),
                    }
                )
            tournament_players[team_reg.event] = players_with_data

    team_notes = []
    player_played_with_team = False
    player_tournament_registrations = set()
    if current_user.is_authenticated and current_user.__class__.__name__ == "Player":
        player_regs = PlayerRegistration.query.filter_by(
            player=current_user.id, team=team_id, status=RegistrationStatus.CONFIRMED
        ).all()
        player_tournament_registrations = {reg.event for reg in player_regs}
        player_played_with_team = len(player_tournament_registrations) > 0

    if current_user.is_authenticated:
        try:
            candidate_notes = (
                MatchNote.query.filter(
                    or_(MatchNote.target == "team1", MatchNote.target == "team2")
                )
                .order_by(MatchNote.created_at.desc())
                .all()
            )
            match_to_points = {}
            for n in candidate_notes:
                m = Match.query.get(n.match)
                if not m:
                    continue
                if not (
                    (n.target == "team1" and m.team1 == team_id)
                    or (n.target == "team2" and m.team2 == team_id)
                ):
                    continue

                can_see_note = False
                if current_user.id == team_id:
                    can_see_note = True
                elif player_played_with_team and current_user.id != team_id:
                    if m.event in player_tournament_registrations:
                        can_see_note = True
                elif current_user.__class__.__name__ == "Player":
                    if can_head_ref_match(m.event, current_user.id, match=m):
                        can_see_note = True

                if not can_see_note:
                    continue

                idx = "-"
                if n.point_id:
                    mid = m.uuid
                    if mid not in match_to_points:
                        pts = (
                            Point.query.filter_by(match=mid).order_by(Point.stamp).all()
                        )
                        match_to_points[mid] = [p.uuid for p in pts]
                    order = match_to_points.get(mid, [])
                    if n.point_id in order:
                        idx = order.index(n.point_id) + 1
                team_notes.append(
                    {
                        "created_at": _dt_iso(n.created_at),
                        "text": n.text,
                        "point_index": str(idx),
                        "match": {
                            "event": m.event,
                            "uuid": m.uuid,
                            "name": m.name,
                        },
                    }
                )
        except Exception:
            team_notes = []
    return jsonify(
        {
            "team": {
                "id": team.id,
                "name": team.name,
                "profile_photo": team.profile_photo,
                "location": team.location,
                "email": team.email,
                "website": team.website,
                "about": team.about,
            },
            "registrations": [
                {
                    "event": r.event,
                    "pseudonym": r.pseudonym,
                    "status": (
                        r.status.value if hasattr(r.status, "value") else str(r.status)
                    ),
                    "paid": bool(r.paid),
                    "amount_paid": r.amount_paid,
                    "start_date": _dt_iso(tournament_start.get(r.event)),
                }
                for r in regs
            ],
            "team_notes": team_notes,
            "tournament_players": tournament_players,
        }
    )


@bp.route("/stones", methods=["GET"])
def stones_list():
    """List stone audio files (for stones player)."""
    import os
    import re
    from flask import current_app

    static_folder = current_app.static_folder
    stones_dir = os.path.join(static_folder, "stones")
    ALLOWED_USERS = os.environ.get("SILLY_USERS", "").split(":")
    mp3_files = []
    if os.path.exists(stones_dir) and os.path.isdir(stones_dir):
        for filename in os.listdir(stones_dir):
            if filename.lower().endswith(".mp3"):
                name_without_ext = os.path.splitext(filename)[0]
                display_name = re.sub(r"^\d+_", "", name_without_ext)
                match = re.match(r"^(\d+)_", name_without_ext)
                sort_order = int(match.group(1)) if match else 999999
                from urllib.parse import quote

                filename_encoded = quote(filename, safe="")
                mp3_files.append(
                    {
                        "filename": filename,
                        "filename_encoded": filename_encoded,
                        "display_name": display_name,
                        "sort_order": sort_order,
                    }
                )
        mp3_files.sort(key=lambda x: (x["sort_order"], x["filename"]))
    user_can_see_all = (
        current_user.is_authenticated and current_user.id in ALLOWED_USERS
    )
    if not user_can_see_all:
        mp3_files = [
            f for f in mp3_files if f["display_name"].lower() in ["classic", "snare"]
        ]
    return jsonify({"stones": mp3_files})


@bp.route("/tournaments/<tournament_url>/matches/<match_id>", methods=["PUT"])
@login_required
def update_match_api(tournament_url, match_id):
    if not _check_to(tournament_url):
        return jsonify({"error": "Forbidden"}), 403

    match = Match.query.filter_by(uuid=match_id, event=tournament_url).first_or_404()
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400

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

    # Validate inputs
    if name:
        match.name = name
    if field is not None:  # field can be empty string/null
        match.field = field

    # Schedule Type
    if schedule_type_str:
        try:
            match.schedule_type = ScheduleType(schedule_type_str)
        except ValueError:
            pass  # Ignore invalid enum

    # Handle BREAK/JOIN clearing teams
    if match.schedule_type in (ScheduleType.BREAK, ScheduleType.JOIN):
        match.team1 = None
        match.team1_initial = None
        match.team2 = None
        match.team2_initial = None
        match.refs = None
        match.refs_initial = None
    else:
        # Teams (helper takes team_name first, then tournament_url)
        if team1_input is not None:
            t1_id, t1_initial = resolve_team_name_to_id(team1_input, tournament_url)
            match.team1 = t1_id
            match.team1_initial = t1_initial

        if team2_input is not None:
            t2_id, t2_initial = resolve_team_name_to_id(team2_input, tournament_url)
            match.team2 = t2_id
            match.team2_initial = t2_initial

        # Refs
        if refs is not None:
            if isinstance(refs, list):
                # Process refs list
                final_refs = []
                final_refs_initial = []
                for r in refs:
                    rid, rinit = resolve_team_name_to_id(r, tournament_url)
                    if rid:
                        final_refs.append(rid)
                    if rinit:
                        final_refs_initial.append(rinit)
                match.refs = ",".join(final_refs) if final_refs else None
                match.refs_initial = (
                    ",".join(final_refs_initial) if final_refs_initial else None
                )
            else:
                # Assume string input if not list
                match.refs_initial = refs

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
        match.nstonesperset = int(stones_per_set)  # Legacy field

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
        prev_id = (
            (previous_match_id or "").strip() if previous_match_id is not None else ""
        )
        if not prev_id:
            return (
                jsonify(
                    {
                        "error": "Previous match is required for Break, Join, Fast, and Safe matches."
                    }
                ),
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

        # Previous match link
        if previous_match_id is not None:
            # If empty string or null, clear it
            if not previous_match_id:
                # If we had a previous match, we need to unlink it properly?
                # update_match_previous_link handles linking.
                # If we want to clear it, we might need manual handling or update_match_previous_link handles it?
                # The helper assumes we are setting a *new* previous match.
                # If previous_match_id is empty, we act as if we are clearing it.
                # The helper doesn't seem to support clearing explicitly easily without a valid ID.
                # But looking at the helper: "prev_match = Match.query.filter_by(uuid=prev_match_id...)"
                # If prev_match_id is None/empty, it returns.
                # But we need to clear match.previous_match.

                # Manual clear if it was set
                if match.previous_match:
                    old_prev = Match.query.filter_by(
                        uuid=match.previous_match, event=tournament_url
                    ).first()
                    if old_prev and old_prev.next_match == match.uuid:
                        old_prev.next_match = match.next_match
                        if match.next_match:
                            old_next = Match.query.filter_by(
                                uuid=match.next_match, event=tournament_url
                            ).first()
                            if old_next:
                                old_next.previous_match = old_prev.uuid
                    elif match.next_match:
                        # Just unlinking from chain
                        old_next = Match.query.filter_by(
                            uuid=match.next_match, event=tournament_url
                        ).first()
                        if old_next:
                            old_next.previous_match = None

                    match.previous_match = None
            else:
                update_match_previous_link(match, previous_match_id, tournament_url)
    else:
        # Dynamic (BREAK, JOIN, FAST, SAFE)
        match.nominal_start_time = compute_dynamic_match_nominal_start_time(
            match, tournament_url
        )
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

    db.session.commit()

    # Recompute all times
    recompute_all_match_times(tournament_url)

    return jsonify({"success": True})


def _check_to(tournament_url):
    if not current_user.is_authenticated:
        return False
    return (
        TO.query.filter_by(
            user_id=current_user.id,
            user_type=current_user.__class__.__name__.lower(),
            event=tournament_url,
        ).first()
        is not None
    )


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
    field_name_for_query = (
        old_field_name if old_field_name != new_field_name else new_field_name
    )
    matches_to_update = Match.query.filter_by(
        event=tournament_url, field=field_name_for_query
    ).all()

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
                    match.camera_stream_starts = (
                        json.dumps(new_stream_starts) if new_stream_starts else None
                    )
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
                        new_ts = calculate_stream_timestamp(
                            point.stamp, stream_starts[camera_idx_str]
                        )
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
            match.camera_stream_starts = (
                json.dumps(stream_starts) if stream_starts else None
            )
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
                if (
                    point.camera_index is not None
                    and point.stamp
                    and str(point.camera_index) in stream_starts
                ):
                    new_ts = calculate_stream_timestamp(
                        point.stamp, stream_starts[str(point.camera_index)]
                    )
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

    # Basic validation
    existing = Match.query.filter_by(event=tournament_url, name=name).first()
    if existing:
        return jsonify({"error": "Match name already exists"}), 400

    match = Match(event=tournament_url, name=name)
    match.field = data.get("field")
    match.nominal_length = (
        int(data.get("length")) if data.get("length") is not None else None
    )

    schedule_type_str = data.get("schedule_type")
    if schedule_type_str:
        try:
            match.schedule_type = ScheduleType(schedule_type_str)
        except ValueError:
            pass

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
                jsonify(
                    {
                        "error": "Previous match is required for Break, Join, Fast, and Safe matches."
                    }
                ),
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
    # Team handling
    team1_input = data.get("team1")
    team2_input = data.get("team2")
    if match.schedule_type not in (ScheduleType.BREAK, ScheduleType.JOIN):
        if team1_input:
            t1_id, t1_initial = resolve_team_name_to_id(team1_input, tournament_url)
            match.team1 = t1_id
            match.team1_initial = t1_initial
        if team2_input:
            t2_id, t2_initial = resolve_team_name_to_id(team2_input, tournament_url)
            match.team2 = t2_id
            match.team2_initial = t2_initial

    # Refs
    refs = data.get("refs")
    if refs and isinstance(refs, list):
        final_refs = []
        final_refs_initial = []
        for r in refs:
            rid, rinit = resolve_team_name_to_id(r, tournament_url)
            if rid:
                final_refs.append(rid)
            if rinit:
                final_refs_initial.append(rinit)
        match.refs = ",".join(final_refs) if final_refs else None
        match.refs_initial = (
            ",".join(final_refs_initial) if final_refs_initial else None
        )

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
        match.nstonesperset = match.stones_per_set

    if data.get("ribbon") is not None:
        match.ribbon = bool(data.get("ribbon"))

    match.skip_condition = data.get("skip_condition")

    db.session.add(match)

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
        match.nominal_start_time = compute_dynamic_match_nominal_start_time(
            match, tournament_url
        )

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
        prev = Match.query.filter_by(
            uuid=match.previous_match, event=tournament_url
        ).first()
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

    tournament = Tournament.query.filter_by(url=tournament_url).first()
    if tournament.num_fields:
        count = Field.query.filter_by(event=tournament_url).count()
        if count >= tournament.num_fields:
            return (
                jsonify({"error": f"Maximum fields ({tournament.num_fields}) reached"}),
                400,
            )

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
        if m.refs_initial:
            for r in (r.strip() for r in m.refs_initial.split(",")):
                if r == tag_ref:
                    used.append(f'Refs of match "{m.name}"')
                    break
        if m.skip_condition and (
            tag_ref in m.skip_condition or tag_name in m.skip_condition
        ):
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
    return jsonify(
        {"tags": [{"id": t.id, "name": t.name, "team": t.team} for t in tags]}
    )


@bp.route("/markdown/<slug>", methods=["GET"])
def markdown_page(slug):
    """Return markdown page content by slug, rendered to HTML with the markdown filter."""
    from app.filters import render_markdown

    mapping = {
        "docs": ("docs.md", "User Docs"),
        "privacy-policy": ("privacy-policy.md", "Privacy Policy"),
        "data-accessibility-guide": (
            "data-accessibility-guide.md",
            "Data Accessibility Guide",
        ),
        "arctos-schedule-script": (
            "arctos-schedule-script.md",
            "Arctos Schedule Script",
        ),
        "thanks": ("thanks.md", "Thanks"),
        "license": ("license.md", "License"),
        "terms": ("terms.md", "Terms and Conditions"),
    }
    if slug not in mapping:
        return jsonify({"error": "Not found"}), 404
    filename, title = mapping[slug]
    path = Path(__file__).parent.parent.parent / "docs" / filename
    if not path.exists():
        return jsonify({"error": "Not found"}), 404
    content = path.read_text(encoding="utf-8")
    html = str(render_markdown(content))
    return jsonify({"title": title, "html": html})


# CSS for .markdown-content (matches python-markdown output: headings, lists, code, tables, etc.)
MARKDOWN_CONTENT_CSS = """
.markdown-content { line-height: 1.6; }
.markdown-content h1, .markdown-content h2, .markdown-content h3,
.markdown-content h4, .markdown-content h5, .markdown-content h6 {
    margin-top: 1em; margin-bottom: 0.5em; font-weight: 600;
}
.markdown-content h1 { font-size: 1.5em; }
.markdown-content h2 { font-size: 1.3em; }
.markdown-content h3 { font-size: 1.15em; }
.markdown-content p { margin-bottom: 0.75em; }
.markdown-content ul, .markdown-content ol { margin-bottom: 0.75em; padding-left: 1.5em; }
.markdown-content li { margin-bottom: 0.25em; }
.markdown-content blockquote {
    border-left: 4px solid var(--bs-secondary, #6c757d);
    padding-left: 1em; margin: 0.75em 0; color: var(--bs-secondary);
}
.markdown-content code { padding: 0.2em 0.4em; font-size: 0.9em; background: rgba(0,0,0,0.06); border-radius: 4px; }
.markdown-content pre { padding: 0.75em; overflow-x: auto; background: rgba(0,0,0,0.06); border-radius: 4px; margin-bottom: 0.75em; }
.markdown-content pre code { padding: 0; background: none; }
.markdown-content table { border-collapse: collapse; margin-bottom: 0.75em; width: 100%; }
.markdown-content th, .markdown-content td { border: 1px solid var(--bs-border-color, #dee2e6); padding: 0.4em 0.6em; text-align: left; }
.markdown-content th { font-weight: 600; background: rgba(0,0,0,0.04); }
.markdown-content a { color: var(--bs-link-color, #0d6efd); text-decoration: none; }
.markdown-content a:hover { text-decoration: underline; }
.markdown-content img { max-width: 100%; height: auto; }
.markdown-content hr { margin: 1em 0; border: 0; border-top: 1px solid var(--bs-border-color, #dee2e6); }
.markdown-content .admonition { margin: 1em 0; padding: 0; border-radius: 6px; border: 1px solid; overflow: hidden; }
.markdown-content .admonition .admonition-title { margin: 0; padding: 0.5em 0.75em; font-weight: 600; }
.markdown-content .admonition p:not(.admonition-title) { padding: 0.5em 0.75em; margin-bottom: 0.5em; }
.markdown-content .admonition p:not(.admonition-title):last-child { margin-bottom: 0; }
.markdown-content .admonition.note { border-color: #0d6efd; background: rgba(13, 110, 253, 0.08); }
.markdown-content .admonition.note .admonition-title { background: rgba(13, 110, 253, 0.2); color: #0a58ca; }
.markdown-content .admonition.warning { border-color: #ffc107; background: rgba(255, 193, 7, 0.12); }
.markdown-content .admonition.warning .admonition-title { background: rgba(255, 193, 7, 0.25); color: #856404; }
.markdown-content .admonition.attention { border-color: #ffc107; background: rgba(255, 193, 7, 0.12); }
.markdown-content .admonition.attention .admonition-title { background: rgba(255, 193, 7, 0.25); color: #856404; }
.markdown-content .admonition.caution { border-color: #fd7e14; background: rgba(253, 126, 20, 0.1); }
.markdown-content .admonition.caution .admonition-title { background: rgba(253, 126, 20, 0.2); color: #b35a0e; }
.markdown-content .admonition.danger { border-color: #dc3545; background: rgba(220, 53, 69, 0.08); }
.markdown-content .admonition.danger .admonition-title { background: rgba(220, 53, 69, 0.2); color: #b02a37; }
.markdown-content .admonition.important { border-color: #fd7e14; background: rgba(253, 126, 20, 0.1); }
.markdown-content .admonition.important .admonition-title { background: rgba(253, 126, 20, 0.2); color: #b35a0e; }
.markdown-content .admonition.tip { border-color: #198754; background: rgba(25, 135, 84, 0.08); }
.markdown-content .admonition.tip .admonition-title { background: rgba(25, 135, 84, 0.2); color: #146c43; }
.markdown-content .admonition.hint { border-color: #198754; background: rgba(25, 135, 84, 0.08); }
.markdown-content .admonition.hint .admonition-title { background: rgba(25, 135, 84, 0.2); color: #146c43; }
"""


@bp.route("/render-markdown", methods=["POST"])
def render_markdown_api():
    """Render markdown to HTML using the same filter as templates (python-markdown + sanitization)."""
    from app.filters import render_markdown as render_markdown_filter

    data = request.get_json()
    if not data or "markdown" not in data:
        return jsonify({"error": "JSON body must include 'markdown'"}), 400
    text = data.get("markdown")
    if text is None:
        text = ""
    elif not isinstance(text, str):
        text = str(text)
    html = str(render_markdown_filter(text))
    return jsonify({"html": html, "css": MARKDOWN_CONTENT_CSS})


@bp.route("/players/<player_id>", methods=["PUT"])
@login_required
def update_player_profile(player_id):
    """Update player profile."""
    if current_user.id != player_id:
        return jsonify({"error": "You can only edit your own profile"}), 403

    player = Player.query.get_or_404(player_id)
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400

    if "name" in data:
        player.name = data["name"]
    if "phone" in data:
        player.phone = data["phone"]
    if "location" in data:
        player.location = data["location"]
    if "bio" in data:
        player.bio = data["bio"]

    db.session.commit()
    return jsonify({"success": True})


@bp.route("/teams/<team_id>", methods=["PUT"])
@login_required
def update_team_profile(team_id):
    """Update team profile."""
    if current_user.id != team_id:
        return jsonify({"error": "You can only edit your own team profile"}), 403

    team = Team.query.get_or_404(team_id)
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400

    if "name" in data:
        team.name = data["name"]
    if "location" in data:
        team.location = data["location"]
    if "email" in data:
        team.email = data["email"]
    if "website" in data:
        team.website = data["website"]
    if "about" in data:
        team.about = data["about"]

    db.session.commit()
    return jsonify({"success": True})


def _profile_photo_upload_dir():
    return os.path.join(current_app.root_path, "..", "static", "uploads", "profiles")


def _safe_profile_photo_filename(prefix, entity_id):
    """Sanitize entity id for use in filename (alphanumeric and underscore only)."""
    safe = "".join(c if c.isalnum() or c == "_" else "_" for c in entity_id)
    return f"{prefix}_{safe}.jpg"


@bp.route("/players/<player_id>/profile-photo", methods=["POST"])
@login_required
def upload_player_profile_photo(player_id):
    """Upload or replace player profile photo. Uses predictable path so overwrites previous."""
    if current_user.id != player_id or current_user.__class__.__name__ != "Player":
        return jsonify({"error": "You can only upload a photo for your own profile"}), 403
    player = Player.query.get_or_404(player_id)
    data = request.get_data()
    if not data or len(data) == 0:
        return jsonify({"error": "No image data"}), 400
    upload_dir = _profile_photo_upload_dir()
    os.makedirs(upload_dir, exist_ok=True)
    # Predictable name: one file per player, always overwritten
    filename = _safe_profile_photo_filename("player", player_id)
    file_path = os.path.join(upload_dir, filename)
    old_path = player.profile_photo
    rel_path = f"uploads/profiles/{filename}"
    try:
        if old_path and old_path != rel_path:
            old_full = os.path.join(current_app.root_path, "..", "static", old_path)
            if os.path.isfile(old_full):
                try:
                    os.remove(old_full)
                except OSError:
                    pass
        with open(file_path, "wb") as f:
            f.write(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    player.profile_photo = rel_path
    db.session.commit()
    return jsonify({"success": True, "path": rel_path})


@bp.route("/teams/<team_id>/profile-photo", methods=["POST"])
@login_required
def upload_team_profile_photo(team_id):
    """Upload or replace team profile photo. Uses predictable path so overwrites previous."""
    if current_user.id != team_id or current_user.__class__.__name__ != "Team":
        return jsonify({"error": "You can only upload a photo for your own team profile"}), 403
    team = Team.query.get_or_404(team_id)
    data = request.get_data()
    if not data or len(data) == 0:
        return jsonify({"error": "No image data"}), 400
    upload_dir = _profile_photo_upload_dir()
    os.makedirs(upload_dir, exist_ok=True)
    filename = _safe_profile_photo_filename("team", team_id)
    file_path = os.path.join(upload_dir, filename)
    old_path = team.profile_photo
    rel_path = f"uploads/profiles/{filename}"
    try:
        if old_path and old_path != rel_path:
            old_full = os.path.join(current_app.root_path, "..", "static", old_path)
            if os.path.isfile(old_full):
                try:
                    os.remove(old_full)
                except OSError:
                    pass
        with open(file_path, "wb") as f:
            f.write(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    team.profile_photo = rel_path
    db.session.commit()
    return jsonify({"success": True, "path": rel_path})


@bp.route("/players/<player_id>/profile-photo", methods=["DELETE"])
@login_required
def delete_player_profile_photo(player_id):
    """Remove player profile photo."""
    if current_user.id != player_id or current_user.__class__.__name__ != "Player":
        return jsonify({"error": "You can only remove a photo from your own profile"}), 403
    player = Player.query.get_or_404(player_id)
    old_path = player.profile_photo
    if old_path:
        old_full = os.path.join(current_app.root_path, "..", "static", old_path)
        if os.path.isfile(old_full):
            try:
                os.remove(old_full)
            except OSError:
                pass
    player.profile_photo = None
    db.session.commit()
    return jsonify({"success": True})


@bp.route("/teams/<team_id>/profile-photo", methods=["DELETE"])
@login_required
def delete_team_profile_photo(team_id):
    """Remove team profile photo."""
    if current_user.id != team_id or current_user.__class__.__name__ != "Team":
        return jsonify({"error": "You can only remove a photo from your own team profile"}), 403
    team = Team.query.get_or_404(team_id)
    old_path = team.profile_photo
    if old_path:
        old_full = os.path.join(current_app.root_path, "..", "static", old_path)
        if os.path.isfile(old_full):
            try:
                os.remove(old_full)
            except OSError:
                pass
    team.profile_photo = None
    db.session.commit()
    return jsonify({"success": True})


@bp.route("/tournaments/<tournament_url>/registrations/player/me", methods=["GET"])
@login_required
def get_my_player_registration(tournament_url):
    """Get current player's registration for this tournament."""
    if current_user.__class__.__name__ != "Player":
        return jsonify({"error": "Only players have player registrations"}), 400

    reg = (
        PlayerRegistration.query.filter_by(event=tournament_url, player=current_user.id)
        .filter(
            PlayerRegistration.status.in_(
                [RegistrationStatus.PENDING_TEAM_APPROVAL, RegistrationStatus.CONFIRMED]
            )
        )
        .first()
    )

    if not reg:
        return jsonify({"error": "Not registered"}), 404

    # Get current team info if any
    current_team = None
    if reg.team:
        team_reg = TeamRegistration.query.filter_by(
            event=tournament_url, team=reg.team, status=RegistrationStatus.CONFIRMED
        ).first()
        if team_reg:
            current_team = {"id": reg.team, "pseudonym": team_reg.pseudonym}

    return jsonify(
        {
            "registration": {
                "id": reg.id,
                "jersey_name": reg.jersey_name,
                "jersey_number": reg.jersey_number,
                "team": reg.team,
                "status": (
                    reg.status.value
                    if hasattr(reg.status, "value")
                    else str(reg.status)
                ),
            },
            "current_team": current_team,
        }
    )


@bp.route("/tournaments/<tournament_url>/registrations/player/me", methods=["PUT"])
@login_required
def update_my_player_registration(tournament_url):
    """Update current player's registration."""
    if current_user.__class__.__name__ != "Player":
        return jsonify({"error": "Only players can edit their registration"}), 400

    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()
    if not tournament.registration_open:
        return jsonify({"error": "Registration changes are locked"}), 403

    reg = (
        PlayerRegistration.query.filter_by(event=tournament_url, player=current_user.id)
        .filter(
            PlayerRegistration.status.in_(
                [RegistrationStatus.PENDING_TEAM_APPROVAL, RegistrationStatus.CONFIRMED]
            )
        )
        .first()
    )

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

    db.session.commit()
    return jsonify({"success": True})


@bp.route("/tournaments/<tournament_url>/registrations/team/me", methods=["GET"])
@login_required
def get_my_team_registration(tournament_url):
    """Get current team's registration for this tournament."""
    if current_user.__class__.__name__ != "Team":
        return jsonify({"error": "Only teams have team registrations"}), 400

    reg = TeamRegistration.query.filter_by(
        event=tournament_url, team=current_user.id, status=RegistrationStatus.CONFIRMED
    ).first()

    if not reg:
        return jsonify({"error": "Not registered"}), 404

    return jsonify(
        {
            "registration": {
                "id": reg.id,
                "pseudonym": reg.pseudonym,
                "status": (
                    reg.status.value
                    if hasattr(reg.status, "value")
                    else str(reg.status)
                ),
            }
        }
    )


@bp.route("/tournaments/<tournament_url>/registrations/team/me", methods=["PUT"])
@login_required
def update_my_team_registration(tournament_url):
    """Update current team's registration."""
    if current_user.__class__.__name__ != "Team":
        return jsonify({"error": "Only teams can edit their registration"}), 400

    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()
    if not tournament.registration_open:
        return jsonify({"error": "Registration changes are locked"}), 403

    reg = TeamRegistration.query.filter_by(
        event=tournament_url, team=current_user.id, status=RegistrationStatus.CONFIRMED
    ).first()

    if not reg:
        return jsonify({"error": "Not registered"}), 404

    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400

    if "pseudonym" in data:
        pseudonym = data["pseudonym"].strip()
        if "::" in pseudonym:
            return jsonify({"error": 'Team pseudonyms cannot contain "::"'}), 400
        if not pseudonym:
            return jsonify({"error": "Team name is required"}), 400
        reg.pseudonym = pseudonym

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
        if m.team1_initial == tag_ref:
            m.team1 = team_id
        if m.team2_initial == tag_ref:
            m.team2 = team_id

        if m.refs_initial:
            refs = [r.strip() for r in m.refs_initial.split(",")]
            current_refs = [r.strip() for r in (m.refs or "").split(",")]
            if len(current_refs) != len(refs):
                current_refs = [""] * len(refs)

            changed = False
            for i, r in enumerate(refs):
                if r == tag_ref:
                    current_refs[i] = team_id
                    changed = True

            if changed:
                m.refs = ",".join(current_refs)

    db.session.commit()
    return jsonify({"success": True})


@bp.route("/tournaments/<tournament_url>/export-schedule", methods=["GET"])
@login_required
def export_schedule_api(tournament_url):
    if not _check_to(tournament_url):
        return jsonify({"error": "Forbidden"}), 403

    from app.error_values import Err, Ok
    from app.services.schedule_import_export_service import ScheduleImportExportService
    from app.utils.responses import json_error
    from app.utils.result_helpers import public_error_message

    res = ScheduleImportExportService.export_schedule(tournament_url)
    match res:
        case Ok(toml_content):
            return jsonify({"toml": toml_content})
        case Err(err):
            status_code = err.status_code if hasattr(err, "status_code") else 400
            return json_error(public_error_message(err), status_code=status_code)


@bp.route("/tournaments/<tournament_url>/import-schedule", methods=["POST"])
@login_required
def import_schedule_api(tournament_url):
    if not _check_to(tournament_url):
        return jsonify({"error": "Forbidden"}), 403

    data = request.get_json()
    toml_content = data.get("toml")
    if not toml_content:
        return jsonify({"error": "TOML content required"}), 400

    from app.error_values import Err, Ok
    from app.services.schedule_import_export_service import ScheduleImportExportService
    from app.utils.responses import json_error
    from app.utils.result_helpers import public_error_message

    res = ScheduleImportExportService.import_schedule(tournament_url, toml_content)
    match res:
        case Ok(_):
            recompute_all_match_times(tournament_url)
            return jsonify({"success": True})
        case Err(err):
            status_code = err.status_code if hasattr(err, "status_code") else 400
            return json_error(public_error_message(err), status_code=status_code)


@bp.route("/<tournament_url>/penalty-types", methods=["GET"])
def get_penalty_types(tournament_url):
    """Get all penalty types for a tournament."""
    types = PenaltyType.query.filter_by(event=tournament_url).all()
    return jsonify({
        "penalty_types": [
            {
                "id": t.id,
                "name": t.name,
                "color": t.color,
                "desc": (t.desc or ""),
            }
            for t in types
        ]
    })


@bp.route("/<tournament_url>/penalty-types", methods=["POST"])
@login_required
def create_penalty_type(tournament_url):
    """Create a new penalty type."""
    if not _check_to(tournament_url):
        return jsonify({"error": "Forbidden"}), 403

    data = request.get_json()
    name = data.get("name")
    if not name:
        return jsonify({"error": "Name required"}), 400

    if len(name) > 50:
        return jsonify({"error": "Name too long"}), 400

    desc = data.get("desc", "")
    color = data.get("color")

    if not color:
        # Assign default color
        existing = PenaltyType.query.filter_by(event=tournament_url).all()
        existing_colors = {t.color for t in existing}
        color = get_next_penalty_color(existing_colors)
    else:
        # Basic validation for hex color
        color = color.strip().lstrip("#")
        if len(color) != 6:
            return jsonify({"error": "Invalid color format"}), 400

    pt = PenaltyType(event=tournament_url, name=name, color=color, desc=desc)
    db.session.add(pt)
    db.session.commit()

    return jsonify({
        "success": True,
        "penalty_type": {
            "id": pt.id,
            "name": pt.name,
            "color": pt.color,
            "desc": (pt.desc or ""),
        },
    })


@bp.route("/<tournament_url>/penalty-types/<int:pt_id>", methods=["PATCH"])
@login_required
def update_penalty_type(tournament_url, pt_id):
    """Update a penalty type."""
    if not _check_to(tournament_url):
        return jsonify({"error": "Forbidden"}), 403

    pt = PenaltyType.query.filter_by(id=pt_id, event=tournament_url).first_or_404()

    data = request.get_json()
    if "name" in data:
        name = data["name"]
        if len(name) > 50:
            return jsonify({"error": "Name too long"}), 400
        pt.name = name
    if "desc" in data:
        pt.desc = data["desc"]
    if "color" in data:
        c = data["color"].strip().lstrip("#")
        if len(c) == 6:
            pt.color = c

    db.session.commit()
    return jsonify({"success": True})


@bp.route("/<tournament_url>/penalty-types/<int:pt_id>", methods=["DELETE"])
@login_required
def delete_penalty_type(tournament_url, pt_id):
    """Delete a penalty type."""
    if not _check_to(tournament_url):
        return jsonify({"error": "Forbidden"}), 403

    pt = PenaltyType.query.filter_by(id=pt_id, event=tournament_url).first_or_404()

    # Check if used
    in_use = MatchNote.query.filter_by(penalty_type_id=pt.id).first()
    if in_use:
        return jsonify({"error": "Cannot delete penalty type that is in use."}), 409

    db.session.delete(pt)
    db.session.commit()
    return jsonify({"success": True})


@bp.route("/<tournament_url>/players/<player_id>/penalty-history", methods=["GET"])
@login_required
def get_player_penalty_history(tournament_url, player_id):
    """List all penalties for a player in this tournament (chronological).
    point_id: the point row from which the user opened the penalties modal; notes
    for that point get is_current_point=True so the UI can show delete only for them.
    """
    if not _check_to(tournament_url):
        return jsonify({"error": "Forbidden"}), 403
    current_match_id = request.args.get("match_id")
    current_point_id = request.args.get("point_id")  # point from which Penalties button was clicked
    notes = (
        db.session.query(MatchNote, Match.name, Point.set_number, MatchNote.created_at)
        .join(Match, MatchNote.match == Match.uuid)
        .filter(
            Match.event == tournament_url,
            MatchNote.target == "player",
            MatchNote.player_id == player_id,
        )
        .outerjoin(Point, MatchNote.point_id == Point.uuid)
        .order_by(MatchNote.created_at.asc())
        .all()
    )
    penalty_type_ids = {n[0].penalty_type_id for n in notes if n[0].penalty_type_id}
    pt_map = {}
    if penalty_type_ids:
        for pt in PenaltyType.query.filter(
            PenaltyType.event == tournament_url,
            PenaltyType.id.in_(penalty_type_ids),
        ).all():
            pt_map[pt.id] = pt.name
    rows = []
    for note, match_name, set_number, created_at in notes:
        pt_name = (
            pt_map.get(note.penalty_type_id) if note.penalty_type_id else (note.text or "Other")
        )
        point_label = f"Set {set_number}" if set_number else "-"
        date_str = created_at.strftime("%m/%d") if created_at else "-"
        is_current = str(note.match) == current_match_id if current_match_id else False
        is_current_point = (
            str(note.point_id) == current_point_id if current_point_id and note.point_id else False
        )
        rows.append(
            {
                "penalty_type_name": pt_name,
                "match_name": match_name or "-",
                "point_label": point_label,
                "date": date_str,
                "is_current_match": is_current,
                "is_current_point": is_current_point,
                "note_uuid": note.uuid,
            }
        )
    return jsonify({"penalties": rows})

