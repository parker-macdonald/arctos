"""Team profile and profile-photo routes.

Hosts the ``teams`` blueprint at ``/_api``:

- ``/teams`` (GET) - list teams.
- ``/teams/<team_id>`` (GET, PUT) - read and edit team profile.
- ``/teams/<team_id>/players`` (GET) - list team members.
- ``/teams/<team_id>/profile-photo`` (POST, DELETE) - upload and
  remove the team's profile photo.
"""

from __future__ import annotations

import os

from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import and_, or_

from app.domain.enums import RegistrationStatus
from app.routes._api import _dt_iso
from app.utils.helpers import can_head_ref_match
from app.utils.profile_photo_helpers import (
    profile_photo_upload_dir,
    safe_profile_photo_filename,
)
from app.utils.user_helpers import is_player, is_team
from models import (
    Match,
    MatchNote,
    Player,
    PlayerRegistration,
    Point,
    Team,
    TeamRegistration,
    Tournament,
    db,
)

bp = Blueprint("teams", __name__, url_prefix="/_api")


@bp.route("/teams", methods=["GET"])
def teams_list():
    """List teams with optional search."""
    search = request.args.get("search", "").strip()
    if search:
        teams = Team.query.filter(Team.name.contains(search) | Team.id.contains(search)).all()
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
    """Players registered for a team in an event or league (public). Event via query param ?event=.
    For leagues use ?event=league:league_url."""
    event_arg = request.args.get("event")
    if not event_arg:
        return jsonify({"error": "event required"}), 400
    team = Team.query.get(team_id)
    if not team:
        return jsonify({"error": "Not found"}), 404
    if event_arg.startswith("league:"):
        league_id = event_arg[7:]
        team_reg = TeamRegistration.query.filter_by(
            team=team_id, league_id=league_id, status=RegistrationStatus.CONFIRMED
        ).first()
        if not team_reg:
            return jsonify({"error": "Not found"}), 404
        accepted_players = PlayerRegistration.query.filter_by(
            league_id=league_id, team=team_id, status=RegistrationStatus.CONFIRMED
        ).all()
    else:
        team_reg = TeamRegistration.query.filter_by(
            team=team_id, event=event_arg, status=RegistrationStatus.CONFIRMED
        ).first()
        if not team_reg:
            return jsonify({"error": "Not found"}), 404
        accepted_players = PlayerRegistration.query.filter_by(
            event=event_arg, team=team_id, status=RegistrationStatus.CONFIRMED
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
    regs = TeamRegistration.query.filter_by(team=team_id, status=RegistrationStatus.CONFIRMED).all()
    event_urls = [r.event for r in regs if r.event]
    tournaments = Tournament.query.filter(Tournament.url.in_(event_urls)).all() if event_urls else []
    tournament_start = {t.url: t.start_date for t in tournaments}

    tournament_players = {}
    if current_user.is_authenticated and current_user.id == team_id and is_team(current_user):
        all_player_ids = set()
        team_reg_to_players = {}
        for team_reg in regs:
            event_key = (
                team_reg.event if team_reg.event else (f"league:{team_reg.league_id}" if team_reg.league_id else None)
            )
            if event_key is None:
                continue
            if team_reg.event:
                accepted_players = PlayerRegistration.query.filter_by(
                    event=team_reg.event,
                    team=team_id,
                    status=RegistrationStatus.CONFIRMED,
                ).all()
            else:
                accepted_players = PlayerRegistration.query.filter_by(
                    league_id=team_reg.league_id,
                    team=team_id,
                    status=RegistrationStatus.CONFIRMED,
                ).all()
            team_reg_to_players[event_key] = accepted_players
            all_player_ids.update(pr.player for pr in accepted_players)

        players_by_id = (
            {p.id: p for p in Player.query.filter(Player.id.in_(list(all_player_ids))).all()} if all_player_ids else {}
        )

        for event_key, accepted_players in team_reg_to_players.items():
            players_with_data = []
            for player_reg in accepted_players:
                player = players_by_id.get(player_reg.player)
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
            tournament_players[event_key] = players_with_data

    team_notes = []
    player_played_with_team = False
    player_tournament_registrations = set()
    if current_user.is_authenticated and is_player(current_user):
        player_regs = PlayerRegistration.query.filter_by(
            player=current_user.id, team=team_id, status=RegistrationStatus.CONFIRMED
        ).all()
        player_tournament_registrations = {reg.event for reg in player_regs}
        player_played_with_team = len(player_tournament_registrations) > 0

    if current_user.is_authenticated:
        try:
            candidate_notes = (
                MatchNote.query.join(Match, Match.uuid == MatchNote.match)
                .filter(
                    or_(
                        and_(MatchNote.target == "team1", Match.team1 == team_id),
                        and_(MatchNote.target == "team2", Match.team2 == team_id),
                    )
                )
                .order_by(MatchNote.created_at.desc())
                .all()
            )
            match_ids = list({n.match for n in candidate_notes})
            matches_by_id = (
                {m.uuid: m for m in Match.query.filter(Match.uuid.in_(match_ids)).all()} if match_ids else {}
            )
            match_to_points = {}
            for n in candidate_notes:
                m = matches_by_id.get(n.match)
                if not m:
                    continue

                can_see_note = False
                if current_user.id == team_id:
                    can_see_note = True
                elif player_played_with_team and current_user.id != team_id:
                    if m.event in player_tournament_registrations:
                        can_see_note = True
                elif is_player(current_user):
                    if can_head_ref_match(m.event, current_user.id, match=m):
                        can_see_note = True

                if not can_see_note:
                    continue

                idx = "-"
                if n.point_id:
                    mid = m.uuid
                    if mid not in match_to_points:
                        pts = Point.query.filter_by(match=mid).order_by(Point.stamp).all()
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
                    "event": r.event or (f"league:{r.league_id}" if r.league_id else ""),
                    "pseudonym": r.pseudonym,
                    "status": (r.status.value if hasattr(r.status, "value") else str(r.status)),
                    "paid": bool(r.paid),
                    "amount_paid": r.amount_paid,
                    "start_date": (_dt_iso(tournament_start.get(r.event)) if r.event else None),
                }
                for r in regs
            ],
            "team_notes": team_notes,
            "tournament_players": tournament_players,
        }
    )


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


@bp.route("/teams/<team_id>/profile-photo", methods=["POST"])
@login_required
def upload_team_profile_photo(team_id):
    """Upload or replace team profile photo. Uses predictable path so overwrites previous."""
    if current_user.id != team_id or not is_team(current_user):
        return (
            jsonify({"error": "You can only upload a photo for your own team profile"}),
            403,
        )
    team = Team.query.get_or_404(team_id)
    data = request.get_data()
    if not data or len(data) == 0:
        return jsonify({"error": "No image data"}), 400
    upload_dir = profile_photo_upload_dir()
    os.makedirs(upload_dir, exist_ok=True)
    filename = safe_profile_photo_filename("team", team_id)
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


@bp.route("/teams/<team_id>/profile-photo", methods=["DELETE"])
@login_required
def delete_team_profile_photo(team_id):
    """Remove team profile photo."""
    if current_user.id != team_id or not is_team(current_user):
        return (
            jsonify({"error": "You can only remove a photo from your own team profile"}),
            403,
        )
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
