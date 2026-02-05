"""
Internal JSON API for the Dioxus SPA. All routes live under /_api/.
Do not use /api/ — that is reserved for a future public API.
"""

from flask import Blueprint, request, jsonify
from flask_login import current_user, login_user, logout_user, login_required
from app.services.tournament_service import TournamentService
from app.utils.helpers import is_valid_url_username, check_tournament_access, can_head_ref_match
from app.domain.enums import RegistrationStatus, MatchStatus
from models import (
    Player,
    Team,
    Tournament,
    Match,
    Point,
    Field,
    TeamRegistration,
    PlayerRegistration,
    TO,
    Injury,
    db,
)

bp = Blueprint("_api", __name__, url_prefix="/_api")


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
        return jsonify(
            {
                "error": "Username must be URL-safe: letters, numbers, hyphens, underscores. Cannot start or end with hyphen or underscore.",
            }
        ), 400
    if Player.query.filter_by(id=username).first() or Team.query.filter_by(id=username).first():
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
    if Player.query.filter_by(id=username).first() or Team.query.filter_by(id=username).first():
        return jsonify({"available": False, "message": "Username already exists"})
    return jsonify({"available": True, "message": "Username is available"})


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
            event=tournament_url, team=team_reg.team, status=RegistrationStatus.CONFIRMED
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
    to_entries = [
        {"user_id": e.user_id, "user_type": e.user_type}
        for e in TO.query.filter_by(event=tournament_url).all()
    ]
    is_current_team_registered = False
    is_current_player_registered = False
    if current_user.is_authenticated:
        if current_user.__class__.__name__ == "Team":
            is_current_team_registered = (
                TeamRegistration.query.filter_by(
                    event=tournament_url, team=current_user.id, status=RegistrationStatus.CONFIRMED
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
                        [RegistrationStatus.PENDING_TEAM_APPROVAL, RegistrationStatus.CONFIRMED]
                    )
                )
                .first()
                is not None
            )
    return jsonify(
        {
            "tournament": _tournament_to_dict(tournament),
            "teams_with_counts": teams_with_counts,
            "unattached_players": unattached,
            "to_entries": to_entries,
            "is_current_team_registered": is_current_team_registered,
            "is_current_player_registered": is_current_player_registered,
        }
    )


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
            team_options.append({"id": tr.team, "pseudonym": tr.pseudonym})
            seen.add(tr.team)
    for m in matches:
        for initial, key in [(m.team1_initial, "team1"), (m.team2_initial, "team2")]:
            if not initial or initial in seen:
                continue
            if "::winner" in initial or "::loser" in initial or " winner" in initial or " loser" in initial:
                continue
            team_options.append({"id": initial, "pseudonym": initial})
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
                "status": m.status.value if hasattr(m.status, "value") else str(m.status),
                "nominal_start_time": _dt_iso(m.nominal_start_time),
                "confirmed_start_time": _dt_iso(m.confirmed_start_time),
                "completed_time": _dt_iso(m.completed_time),
                "schedule_type": m.schedule_type.value if m.schedule_type else None,
                "set_type": m.set_type.value if m.set_type else None,
            }
        )
    return jsonify(
        {"tournament": _tournament_to_dict(tournament), "matches": match_list, "fields": fields, "team_options": team_options}
    )


@bp.route("/tournaments/<tournament_url>/results", methods=["GET"])
def tournament_results(tournament_url):
    """Completed/skipped matches and points."""
    tournament, err = _require_tournament(tournament_url)
    if err:
        return jsonify({"error": "Not found"}), err
    matches = Match.query.filter(
        Match.event == tournament_url,
        Match.status.in_([MatchStatus.COMPLETED, MatchStatus.SKIPPED]),
    ).all()
    points_by_match = {}
    if matches:
        match_ids = [m.uuid for m in matches]
        for p in Point.query.filter(Point.match.in_(match_ids)).all():
            points_by_match.setdefault(p.match, []).append(
                {
                    "uuid": p.uuid,
                    "set_number": p.set_number,
                    "winner": p.winner,
                    "rerolled": p.rerolled,
                }
            )
    match_list = []
    for m in matches:
        match_list.append(
            {
                "uuid": m.uuid,
                "name": m.name,
                "field": m.field,
                "team1": m.team1,
                "team2": m.team2,
                "match_winner": m.match_winner.value if m.match_winner else None,
                "points": points_by_match.get(m.uuid, []),
            }
        )
    return jsonify({"tournament": _tournament_to_dict(tournament), "matches": match_list})


@bp.route("/tournaments/<tournament_url>/fields", methods=["GET"])
def tournament_fields(tournament_url):
    """List fields for a tournament."""
    tournament, err = _require_tournament(tournament_url)
    if err:
        return jsonify({"error": "Not found"}), err
    fields = Field.query.filter_by(event=tournament_url).order_by(Field.name).all()
    return jsonify(
        {
            "fields": [
                {"id": f.id, "name": f.name, "camera": f.camera}
                for f in fields
            ]
        }
    )


def _team_name_for_match(tournament_url, match, team_key):
    team_id = getattr(match, team_key)
    if not team_id:
        initial = getattr(match, f"{team_key}_initial", None)
        return initial or f"Team {team_key[-1]}"
    reg = TeamRegistration.query.filter_by(
        event=tournament_url, team=team_id
    ).first()
    if reg and reg.pseudonym:
        return reg.pseudonym
    t = Team.query.get(team_id)
    return t.name if t else team_id


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
        }
        for p in points
    ]
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
                "status": match.status.value if hasattr(match.status, "value") else str(match.status),
                "nominal_start_time": _dt_iso(match.nominal_start_time),
                "confirmed_start_time": _dt_iso(match.confirmed_start_time),
                "completed_time": _dt_iso(match.completed_time),
                "set_type": match.set_type.value if match.set_type else None,
                "stones_per_set": match.stones_per_set,
                "stones_remaining": match.stones_remaining,
                "match_winner": match.match_winner.value if match.match_winner else None,
            },
            "points": points_data,
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
    players = q.order_by(Player.name.asc()).offset((page - 1) * per_page).limit(per_page).all()
    return jsonify(
        {
            "players": [{"id": p.id, "name": p.name, "profile_photo": p.profile_photo} for p in players],
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
    injuries_q = Injury.query.filter_by(player=player_id).order_by(Injury.stamp.desc()).all()
    can_see_private = current_user.is_authenticated and current_user.id == player_id
    injuries = []
    for inj in injuries_q:
        if inj.show or can_see_private:
            injuries.append(
                {
                    "id": inj.id,
                    "message": inj.message,
                    "stamp": _dt_iso(getattr(inj, "stamp", None)),
                    "active": getattr(inj, "active", False),
                    "show": getattr(inj, "show", False),
                }
            )
    return jsonify(
        {
            "player": {
                "id": player.id,
                "name": player.name,
                "profile_photo": player.profile_photo,
                "phone": player.phone
                if (current_user.is_authenticated and current_user.id == player_id)
                else None,
                "location": player.location,
                "bio": player.bio,
            },
            "registrations": [
                {
                    "event": r.event,
                    "team": r.team,
                    "status": r.status.value if hasattr(r.status, "value") else str(r.status),
                }
                for r in regs
            ],
            "injuries": injuries,
        }
    )


@bp.route("/players/<player_id>/injuries", methods=["GET"])
@login_required
def player_injuries(player_id):
    """List injuries for the current player (owner only)."""
    if current_user.id != player_id or current_user.__class__.__name__ != "Player":
        return jsonify({"error": "Forbidden"}), 403
    injuries = (
        Injury.query.filter_by(player=player_id)
        .order_by(Injury.stamp.desc())
        .all()
    )
    return jsonify(
        {
            "injuries": [
                {
                    "id": inj.id,
                    "message": inj.message,
                    "stamp": _dt_iso(getattr(inj, "stamp", None)),
                    "active": getattr(inj, "active", False),
                    "show": getattr(inj, "show", False),
                }
                for inj in injuries
            ]
        }
    )


@bp.route("/players/<player_id>/injuries", methods=["POST"])
@login_required
def add_injury_api(player_id):
    """Create a new injury for the current player."""
    if current_user.id != player_id or current_user.__class__.__name__ != "Player":
        return jsonify({"error": "Forbidden"}), 403
    if not request.is_json:
        return jsonify({"error": "Content-Type must be application/json"}), 415
    data = request.get_json() or {}
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"error": "message is required"}), 400
    active = bool(data.get("active", True))
    show = bool(data.get("show", True))
    date_str = data.get("date")
    inj = Injury(player=player_id, message=message, active=active, show=show)
    if date_str:
        try:
            from datetime import datetime

            inj.stamp = datetime.strptime(date_str, "%Y-%m-%d")
        except Exception:
            return jsonify({"error": "Invalid date format, expected YYYY-MM-DD"}), 400
    db.session.add(inj)
    db.session.commit()
    return (
        jsonify(
            {
                "id": inj.id,
                "message": inj.message,
                "stamp": _dt_iso(getattr(inj, "stamp", None)),
                "active": getattr(inj, "active", False),
                "show": getattr(inj, "show", False),
            }
        ),
        201,
    )


@bp.route("/players/<player_id>/injuries/<int:injury_id>", methods=["GET"])
@login_required
def get_injury_api(player_id, injury_id):
    """Get a single injury (owner only)."""
    if current_user.id != player_id or current_user.__class__.__name__ != "Player":
        return jsonify({"error": "Forbidden"}), 403
    inj = Injury.query.filter_by(id=injury_id, player=player_id).first()
    if not inj:
        return jsonify({"error": "Not found"}), 404
    return jsonify(
        {
            "id": inj.id,
            "message": inj.message,
            "stamp": _dt_iso(getattr(inj, "stamp", None)),
            "active": getattr(inj, "active", False),
            "show": getattr(inj, "show", False),
        }
    )


@bp.route("/players/<player_id>/injuries/<int:injury_id>", methods=["PUT"])
@login_required
def update_injury_api(player_id, injury_id):
    """Update an injury (owner only)."""
    if current_user.id != player_id or current_user.__class__.__name__ != "Player":
        return jsonify({"error": "Forbidden"}), 403
    inj = Injury.query.filter_by(id=injury_id, player=player_id).first()
    if not inj:
        return jsonify({"error": "Not found"}), 404
    if not request.is_json:
        return jsonify({"error": "Content-Type must be application/json"}), 415
    data = request.get_json() or {}
    message = data.get("message")
    if message is not None:
        message = message.strip()
        if not message:
            return jsonify({"error": "message is required"}), 400
        inj.message = message
    if "active" in data:
        inj.active = bool(data.get("active"))
    if "show" in data:
        inj.show = bool(data.get("show"))
    if "date" in data:
        date_str = data.get("date")
        if date_str:
            try:
                from datetime import datetime

                inj.stamp = datetime.strptime(date_str, "%Y-%m-%d")
            except Exception:
                return jsonify({"error": "Invalid date format, expected YYYY-MM-DD"}), 400
    db.session.commit()
    return jsonify(
        {
            "id": inj.id,
            "message": inj.message,
            "stamp": _dt_iso(getattr(inj, "stamp", None)),
            "active": getattr(inj, "active", False),
            "show": getattr(inj, "show", False),
        }
    )


@bp.route("/players/<player_id>/injuries/<int:injury_id>", methods=["DELETE"])
@login_required
def delete_injury_api(player_id, injury_id):
    """Delete an injury (owner only)."""
    if current_user.id != player_id or current_user.__class__.__name__ != "Player":
        return jsonify({"error": "Forbidden"}), 403
    inj = Injury.query.filter_by(id=injury_id, player=player_id).first()
    if not inj:
        return jsonify({"error": "Not found"}), 404
    db.session.delete(inj)
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
        {"teams": [{"id": t.id, "name": t.name, "profile_photo": t.profile_photo} for t in teams]}
    )


@bp.route("/teams/<team_id>", methods=["GET"])
def team_profile(team_id):
    """Team profile (public)."""
    team = Team.query.get(team_id)
    if not team:
        return jsonify({"error": "Not found"}), 404
    regs = TeamRegistration.query.filter_by(team=team_id, status=RegistrationStatus.CONFIRMED).all()
    return jsonify(
        {
            "team": {
                "id": team.id,
                "name": team.name,
                "profile_photo": team.profile_photo,
            },
            "registrations": [{"event": r.event, "pseudonym": r.pseudonym} for r in regs],
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
    user_can_see_all = current_user.is_authenticated and current_user.id in ALLOWED_USERS
    if not user_can_see_all:
        mp3_files = [f for f in mp3_files if f["display_name"].lower() in ["classic", "snare"]]
    return jsonify({"stones": mp3_files})


@bp.route("/server-time", methods=["GET"])
def server_time():
    """Server time (unix timestamp)."""
    import time
    from datetime import datetime, timezone
    return jsonify({"server_time": time.time(), "timestamp": datetime.now(timezone.utc).isoformat()})
