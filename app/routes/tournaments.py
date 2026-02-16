"""
Tournament management routes.
"""

from tracemalloc import start
from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    flash,
    jsonify,
    current_app,
)
from flask_login import login_required, current_user
from flask_executor import Executor

from datetime import datetime, timedelta, timezone
import json

from flask_login.utils import urlencode
from urllib3.util import url
from models import (
    Tournament,
    Match,
    Field,
    Tag,
    TeamRegistration,
    PlayerRegistration,
    Team,
    TO,
    db,
)
from app.utils.helpers import (
    check_tournament_access,
    resolve_team_name_to_id,
    resolve_tag_to_team,
    validate_permission_key,
)
from app.utils.scheduling import (
    compute_dynamic_match_nominal_start_time,
    validate_match_input,
    recompute_all_match_times,
    detect_match_conflicts,
)
from app.utils.decorators import require_tournament_organizer
from app.filters import is_head_ref

from os import path

from app.utils.footage import finalize_recording_worker
from app.utils.camera_helpers import (
    generate_camera_key,
    validate_camera_key,
    get_camera_key_from_request,
    require_camera_key,
)

from app.domain.enums import (
    MatchStatus,
    RegistrationStatus,
    ScheduleType,
    SetType,
)

# for finalizing recordings which calls ffmpeg
# only one worker bc ffmpeg does its own parallelism
# so we only ever want to run one at a time
executor = Executor()

bp = Blueprint("tournaments", __name__)


def update_match_previous_link(
    match: Match, prev_match_id: str, tournament_url: str, is_new: bool = False
) -> None:
    """
    Update the previous_match link for a match, maintaining a doubly linked list structure.

    When inserting a match after prev_match, if prev_match already has a next_match:
    1. Store the old next_match of prev_match
    2. Set the current match's previous_match to prev_match
    3. Set prev_match's next_match to the current match
    4. Set the current match's next_match to the old next_match (if it existed)
    5. Set the old next_match's previous_match to the current match (if it existed)
    6. If updating (not new), handle cleanup of old previous_match's next_match

    This properly inserts the match into the chain: ... -> prev_match -> match -> old_next_match -> ...

    Args:
        match: The match to update
        prev_match_id: UUID of the match to set as previous_match
        tournament_url: Tournament URL for validation
        is_new: True if this is a new match, False if updating existing match
    """
    prev_match = Match.query.filter_by(uuid=prev_match_id, event=tournament_url).first()
    if not prev_match:
        return

    # Store old previous_match and next_match for cleanup (only for updates)
    old_prev_id = match.previous_match if not is_new else None
    old_next_id = match.next_match if not is_new else None

    # Store the old next_match of prev_match (before we change it)
    prev_match_old_next_id = prev_match.next_match

    # Set the current match's previous_match to prev_match
    match.previous_match = prev_match_id

    # Set prev_match's next_match to this match
    prev_match.next_match = match.uuid

    # If prev_match had a next_match that isn't this match, link it to this match
    if prev_match_old_next_id and prev_match_old_next_id != match.uuid:
        prev_match_old_next = Match.query.filter_by(
            uuid=prev_match_old_next_id, event=tournament_url
        ).first()
        if prev_match_old_next:
            # Set the current match's next_match to the old next_match
            match.next_match = prev_match_old_next_id
            # Set the old next_match's previous_match to this match
            prev_match_old_next.previous_match = match.uuid
    else:
        # No old next_match from prev_match
        # If updating an existing match, preserve its existing next_match if it's still valid
        # (only clear if this is a new match or if we're explicitly changing the chain)
        if is_new:
            match.next_match = None
        # For updates, preserve the existing next_match - it will be handled by cleanup logic below if needed

    # If updating and had an old previous_match, handle cleanup
    if old_prev_id and old_prev_id != prev_match_id:
        old_prev_match = Match.query.filter_by(
            uuid=old_prev_id, event=tournament_url
        ).first()
        if old_prev_match:
            # If old_prev_match's next_match pointed to this match, we need to update it
            if old_prev_match.next_match == match.uuid:
                # The old previous match's next should now point to this match's old next (if any)
                old_prev_match.next_match = (
                    old_next_id if old_next_id != old_prev_id else None
                )
                # If we set old_prev_match.next_match to something, update that match's previous_match
                if old_prev_match.next_match:
                    old_next_of_old_prev = Match.query.filter_by(
                        uuid=old_prev_match.next_match, event=tournament_url
                    ).first()
                    if old_next_of_old_prev:
                        old_next_of_old_prev.previous_match = old_prev_id

    # If updating and had an old next_match that we didn't preserve, handle cleanup
    if old_next_id and old_next_id != match.next_match:
        old_next_match = Match.query.filter_by(
            uuid=old_next_id, event=tournament_url
        ).first()
        if old_next_match and old_next_match.previous_match == match.uuid:
            # This match's old next_match no longer has this match as its previous
            old_next_match.previous_match = None


def is_not_TO(
    tournament_url, message="Only tournament organizers can access this page"
):
    """
    Legacy helper retained for compatibility.

    Prefer `@require_tournament_organizer()` going forward.
    """
    from app.services.permission_service import PermissionService

    if not PermissionService.is_tournament_organizer(tournament_url, current_user):
        flash(message, "error")
        return True
    return False


@bp.route("/new-tournament")
@login_required
def new_tournament():
    """Create new tournament page."""
    return render_template("new_tournament.html")


@bp.route("/create-tournament", methods=["POST"])
@login_required
def create_tournament():
    """Create a new tournament."""
    name = request.form["name"]
    url = request.form["url"]
    permission_key = request.form.get("permission_key", "").strip()

    # Validate permission key
    if not validate_permission_key(url, permission_key):
        flash(
            "Invalid permission key. Please contact reid@xz.ax to request a permission key for your tournament URL slug.",
            "error",
        )
        return redirect("/new-tournament")

    if Tournament.query.filter_by(url=url).first():
        flash("Tournament URL already exists", "error")
        return redirect("/new-tournament")

    tournament = Tournament(
        url=url,
        name=name,
        start_date=datetime.now(timezone.utc).replace(tzinfo=None),
        end_date=None,
    )

    db.session.add(tournament)

    to_entry = TO(
        user_id=current_user.id,
        user_type=current_user.__class__.__name__.lower(),
        event=url,
    )
    db.session.add(to_entry)
    db.session.commit()

    flash(f'Tournament "{name}" created successfully!', "success")
    return redirect(f"/{url}")


@bp.route("/<tournament_url>")
def tournament_home(tournament_url):
    """Tournament homepage."""
    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()

    if not tournament.published:
        if not current_user.is_authenticated:
            flash("This tournament is not yet published", "error")
            return redirect("/")

        is_to = TO.query.filter_by(
            user_id=current_user.id,
            user_type=current_user.__class__.__name__.lower(),
            event=tournament_url,
        ).first()

        if not is_to:
            flash("This tournament is not yet published", "error")
            return redirect("/")

    team_registrations = TeamRegistration.query.filter_by(
        event=tournament_url, status=RegistrationStatus.CONFIRMED
    ).all()

    teams_with_counts = []
    for team_reg in team_registrations:
        player_count = PlayerRegistration.query.filter_by(
            event=tournament_url,
            team=team_reg.team,
            status=RegistrationStatus.CONFIRMED,
        ).count()

        team = Team.query.get(team_reg.team)
        teams_with_counts.append(
            {"team_registration": team_reg, "player_count": player_count, "team": team}
        )

    unattached_players = []
    player_registrations = PlayerRegistration.query.filter_by(
        event=tournament_url, team=None, status=RegistrationStatus.CONFIRMED
    ).all()

    for player_reg in player_registrations:
        from models import Player

        player = Player.query.get(player_reg.player)
        if player:
            unattached_players.append({"registration": player_reg, "player": player})

    to_entries = TO.query.filter_by(event=tournament_url).all()

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
        elif current_user.__class__.__name__ == "Player":
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

    return render_template(
        "tournament_home.html",
        tournament=tournament,
        teams_with_counts=teams_with_counts,
        unattached_players=unattached_players,
        to_entries=to_entries,
        is_current_team_registered=is_current_team_registered,
        is_current_player_registered=is_current_player_registered,
    )


@bp.route("/<tournament_url>/schedule")
def tournament_schedule(tournament_url):
    """Tournament schedule page."""
    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()

    from app.utils.helpers import can_head_ref_match

    is_head_ref_flag = False
    if current_user.is_authenticated and current_user.__class__.__name__ == "Player":
        is_head_ref_flag = can_head_ref_match(
            tournament_url, current_user.id, match=None
        )

    if not tournament.schedule_published:
        if not current_user.is_authenticated:
            flash("The tournament schedule is not yet published", "error")
            return redirect(f"/{tournament_url}")

        is_to = TO.query.filter_by(
            user_id=current_user.id,
            user_type=current_user.__class__.__name__.lower(),
            event=tournament_url,
        ).first()

        if not is_to and not is_head_ref_flag:
            flash("The tournament schedule is not yet published", "error")
            return redirect(f"/{tournament_url}")

    matches = (
        Match.query.filter_by(event=tournament_url)
        .order_by(Match.nominal_start_time)
        .all()
    )
    fields = Field.query.filter_by(event=tournament_url).order_by(Field.name).all()

    # Optional filters/highlighting
    filter_field = request.args.get("field", "").strip() or None
    highlight_team = request.args.get("team", "").strip() or None

    # Get all teams for autocomplete (team IDs and pseudonyms)
    from models import TeamRegistration

    team_registrations = TeamRegistration.query.filter_by(
        event=tournament_url, status=RegistrationStatus.CONFIRMED
    ).all()

    # Build list of team options (ID and pseudonym)
    team_options = []
    seen_teams = set()
    for team_reg in team_registrations:
        if team_reg.team not in seen_teams:
            team_options.append({"id": team_reg.team, "pseudonym": team_reg.pseudonym})
            seen_teams.add(team_reg.team)

    # Also include any team IDs/pseudonyms from match initial values
    for match in matches:
        if match.team1_initial and match.team1_initial not in seen_teams:
            # Check if it's a dependency reference (ends with "::winner", "::loser", or legacy " winner"/" loser")
            if not (
                match.team1_initial.endswith("::winner")
                or match.team1_initial.endswith("::loser")
                or match.team1_initial.endswith(" winner")
                or match.team1_initial.endswith(" loser")
            ):
                team_options.append(
                    {"id": match.team1_initial, "pseudonym": match.team1_initial}
                )
                seen_teams.add(match.team1_initial)
        if match.team2_initial and match.team2_initial not in seen_teams:
            # Check if it's a dependency reference (ends with "::winner", "::loser", or legacy " winner"/" loser")
            if not (
                match.team2_initial.endswith("::winner")
                or match.team2_initial.endswith("::loser")
                or match.team2_initial.endswith(" winner")
                or match.team2_initial.endswith(" loser")
            ):
                team_options.append(
                    {"id": match.team2_initial, "pseudonym": match.team2_initial}
                )
                seen_teams.add(match.team2_initial)

    return render_template(
        "tournament_schedule.html",
        tournament=tournament,
        matches=matches,
        fields=fields,
        is_head_ref=is_head_ref_flag,
        filter_field=filter_field,
        highlight_team=highlight_team,
        team_options=team_options,
    )


@bp.route("/<tournament_url>/results")
def tournament_results(tournament_url):
    """Tournament results page."""
    has_access, tournament = check_tournament_access(tournament_url)
    if not has_access or not tournament:
        return redirect("/")

    from models import Point

    matches = Match.query.filter(
        Match.event == tournament_url,
        Match.status.in_([MatchStatus.COMPLETED, MatchStatus.SKIPPED]),
    ).all()
    points_by_match = {}
    if matches:
        match_ids = [m.uuid for m in matches]
        all_points = Point.query.filter(Point.match.in_(match_ids)).all()
        for p in all_points:
            points_by_match.setdefault(p.match, []).append(p)
    return render_template(
        "tournament_results.html",
        tournament=tournament,
        matches=matches,
        points_by_match=points_by_match,
    )


@bp.route("/<tournament_url>/bracket")
def tournament_bracket(tournament_url):
    """Tournament bracket visualization page."""
    has_access, tournament = check_tournament_access(tournament_url)
    if not has_access or not tournament:
        return redirect("/")

    # Check if user is a TO
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

    # Only show bracket if bracket data exists and (schedule is published or user is TO)
    if not tournament.bracket:
        flash("Bracket is not available", "error")
        return redirect(f"/{tournament_url}")

    if not tournament.schedule_published and not is_to:
        flash("Bracket is not available", "error")
        return redirect(f"/{tournament_url}")

    try:
        import tomli

        bracket_data = tomli.loads(tournament.bracket)
    except Exception as e:
        flash(f"Error parsing bracket data: {str(e)}", "error")
        return redirect(f"/{tournament_url}")

    # Process brackets and resolve team references
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

            # Resolve team reference
            team_info = None
            is_reference = False
            is_tag = False
            match_name = None

            # Check if it's a tag reference first: tag::TAG_NAME
            if team_ref.lower().startswith("tag::"):
                tag_name = team_ref[5:].strip()
                if tag_name:
                    tag = Tag.query.filter_by(
                        event=tournament_url, name=tag_name
                    ).first()
                    if tag and tag.team:
                        # Tag has a team assigned - resolve it
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
                            team_info = {
                                "display_text": f"tag::{tag_name}",
                            }
                            is_tag = True
                    elif tag:
                        # Tag exists but no team assigned
                        team_info = {
                            "display_text": f"tag::{tag_name}",
                        }
                        is_tag = True
            # Check if it's a match reference (match_name::winner or match_name::loser)
            elif "::" in team_ref:
                parts = team_ref.split("::", 1)
                match_name = parts[0].strip()
                ref_type = parts[1].strip() if len(parts) > 1 else ""

                # Find the match
                match = Match.query.filter_by(
                    event=tournament_url, name=match_name
                ).first()
                if (
                    match
                    and match.status == MatchStatus.COMPLETED
                    and match.match_winner
                ):
                    # Determine winner/loser team
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
                    # Match exists but not completed - show reference text
                    team_info = {"display_text": team_ref.replace("::", " ")}
                    is_reference = True
                else:
                    # Match doesn't exist - show reference text anyway
                    team_info = {"display_text": team_ref.replace("::", " ")}
                    is_reference = True
            # Check if it's a team ID
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
                    # Backwards-compat: legacy plain tag name without 'tag::' prefix
                    tag = Tag.query.filter_by(
                        event=tournament_url, name=team_ref
                    ).first()
                    if tag and tag.team:
                        # Tag has a team assigned - resolve it
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
                        # Tag exists but no team assigned
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

    return render_template(
        "tournament_bracket.html", tournament=tournament, brackets=processed_brackets
    )


@bp.route("/<tournament_url>/bracket-setup")
@login_required
def bracket_setup(tournament_url):
    """Bracket setup page for TOs."""
    if is_not_TO(tournament_url):
        return redirect(f"/{tournament_url}")

    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()

    # Parse existing bracket data if it exists
    brackets_data = []
    if tournament.bracket:
        try:
            import tomli

            parsed = tomli.loads(tournament.bracket)
            brackets_data = parsed.get("brackets", [])
        except Exception:
            pass

    # Get matches for reference dropdown
    matches = Match.query.filter_by(event=tournament_url).order_by(Match.name).all()

    # Get teams for team selection
    team_registrations = TeamRegistration.query.filter_by(
        event=tournament_url, status=RegistrationStatus.CONFIRMED
    ).all()

    # Get tags
    tags = Tag.query.filter_by(event=tournament_url).order_by(Tag.name).all()

    return render_template(
        "bracket_setup.html",
        tournament=tournament,
        brackets_data=brackets_data,
        matches=matches,
        team_registrations=team_registrations,
        tags=tags,
    )


@bp.route("/<tournament_url>/bracket-setup", methods=["POST"])
@login_required
def update_bracket_setup(tournament_url):
    """Update bracket configuration."""
    if is_not_TO(tournament_url):
        return redirect(f"/{tournament_url}")

    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()

    import tomli
    import os
    from flask import current_app
    from datetime import datetime

    # Handle image uploads first
    bracket_images = {}
    if "bracket_images" in request.files:
        files = request.files.getlist("bracket_images")
        bracket_indices = request.form.getlist("bracket_image_indices")

        for idx, file in enumerate(files):
            if file and file.filename:
                bracket_idx = (
                    bracket_indices[idx] if idx < len(bracket_indices) else None
                )
                if bracket_idx is not None:
                    try:
                        upload_dir = os.path.join(
                            current_app.root_path, "../static", "uploads", "brackets"
                        )
                        os.makedirs(upload_dir, exist_ok=True)
                        filename = f"bracket_{tournament_url}_{bracket_idx}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.{file.filename.split('.')[-1]}"
                        file_path = os.path.join(upload_dir, filename)
                        file.save(file_path)
                        bracket_images[bracket_idx] = f"uploads/brackets/{filename}"
                    except Exception as e:
                        flash(f"Error uploading image: {str(e)}", "error")

    # Build TOML structure from form data
    brackets = []
    bracket_count = int(request.form.get("bracket_count", 0))

    for i in range(bracket_count):
        bracket_name = request.form.get(f"bracket_{i}_name", "").strip()
        if not bracket_name:
            continue

        # Use uploaded image or existing image path
        bracket_image = bracket_images.get(str(i))
        if not bracket_image:
            bracket_image = request.form.get(f"bracket_{i}_image_existing", "").strip()

        if not bracket_image:
            continue

        teams = []
        # Count teams by checking for team ref inputs
        team_count = 0
        while request.form.get(f"bracket_{i}_team_{team_count}_ref"):
            team_count += 1

        for j in range(team_count):
            team_ref = request.form.get(f"bracket_{i}_team_{j}_ref", "").strip()
            if not team_ref:
                continue

            try:
                x = int(request.form.get(f"bracket_{i}_team_{j}_x", 0))
                y = int(request.form.get(f"bracket_{i}_team_{j}_y", 0))
                halign = request.form.get(f"bracket_{i}_team_{j}_halign", "center")
                valign = request.form.get(f"bracket_{i}_team_{j}_valign", "center")
                size = int(request.form.get(f"bracket_{i}_team_{j}_size", 20))
            except (ValueError, TypeError):
                continue

            teams.append(
                {
                    "team": team_ref,
                    "x": x,
                    "y": y,
                    "halign": halign,
                    "valign": valign,
                    "size": size,
                }
            )

        brackets.append({"name": bracket_name, "image": bracket_image, "teams": teams})

    # Generate TOML manually (simple structure)
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
        toml_lines.append("[[brackets]]")
        toml_lines.append(f'name = "{escape_toml_string(bracket["name"])}"')
        toml_lines.append(f'image = "{escape_toml_string(bracket["image"])}"')
        toml_lines.append("")
        for team in bracket.get("teams", []):
            toml_lines.append("[[brackets.teams]]")
            toml_lines.append(f'team = "{escape_toml_string(team["team"])}"')
            toml_lines.append(f'x = {team["x"]}')
            toml_lines.append(f'y = {team["y"]}')
            toml_lines.append(f'halign = "{escape_toml_string(team["halign"])}"')
            toml_lines.append(f'valign = "{escape_toml_string(team["valign"])}"')
            toml_lines.append(f'size = {team["size"]}')
            toml_lines.append("")
    toml_str = "\n".join(toml_lines)

    tournament.bracket = toml_str
    db.session.commit()

    flash("Bracket configuration updated successfully!", "success")
    return redirect(f"/{tournament_url}/bracket-setup")


@bp.route("/<tournament_url>/settings")
@require_tournament_organizer(
    "You do not have permission to access tournament settings"
)
def tournament_settings(tournament_url):
    """Tournament settings page."""
    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()

    # Get all TOs for this tournament with their user info
    from models import Player, Team

    to_entries = TO.query.filter_by(event=tournament_url).all()
    tos_with_info = []
    for to_entry in to_entries:
        if to_entry.user_type == "player":
            user = Player.query.get(to_entry.user_id)
            user_name = user.name if user else to_entry.user_id
        else:  # team
            user = Team.query.get(to_entry.user_id)
            user_name = user.name if user else to_entry.user_id

        tos_with_info.append(
            {
                "to": to_entry,
                "user": user,
                "user_name": user_name,
                "is_current_user": to_entry.user_id == current_user.id
                and to_entry.user_type == current_user.__class__.__name__.lower(),
            }
        )

    return render_template(
        "tournament_settings.html", tournament=tournament, tos_with_info=tos_with_info
    )


@bp.route("/<tournament_url>/setup")
@login_required
def tournament_setup(tournament_url):
    """Tournament setup page."""
    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()

    if is_not_TO(tournament_url):
        return redirect(f"/{tournament_url}")

    from sqlalchemy.orm import joinedload

    matches = (
        Match.query.options(
            joinedload(Match.previous_match_obj), joinedload(Match.next_match_obj)
        )
        .filter_by(event=tournament_url)
        .order_by(Match.nominal_start_time)
        .all()
    )
    fields = Field.query.filter_by(event=tournament_url).all()
    tags = Tag.query.filter_by(event=tournament_url).all()
    # Only confirmed teams should be eligible for tag-to-team conversion.
    team_registrations = TeamRegistration.query.filter_by(
        event=tournament_url, status=RegistrationStatus.CONFIRMED
    ).all()

    # Detect conflicts across all matches; template expects dict match_uuid -> list of description strings
    raw_conflicts = detect_match_conflicts(tournament_url)
    name_to_uuids = {}
    for m in matches:
        name_to_uuids.setdefault(m.name, []).append(m.uuid)
    conflicts = {}
    for c in raw_conflicts:
        desc1 = f"Overlaps with {c['match2']} on {c['field']}"
        desc2 = f"Overlaps with {c['match1']} on {c['field']}"
        for uid in name_to_uuids.get(c["match1"], []):
            conflicts.setdefault(uid, []).append(desc1)
        for uid in name_to_uuids.get(c["match2"], []):
            conflicts.setdefault(uid, []).append(desc2)

    return render_template(
        "tournament_setup.html",
        tournament=tournament,
        matches=matches,
        fields=fields,
        tags=tags,
        team_registrations=team_registrations,
        conflicts=conflicts,
    )


@bp.route("/<tournament_url>/recompute-schedule", methods=["POST"])
@login_required
def recompute_schedule(tournament_url):
    """Force full recompute of match times as if a match were just edited (TO only)."""
    if is_not_TO(tournament_url):
        return redirect(f"/{tournament_url}")
    try:
        recompute_all_match_times(tournament_url)
        flash("Schedule recomputed successfully.", "success")
    except Exception as e:
        flash(f"Recompute failed: {e}", "error")
    return redirect(f"/{tournament_url}/setup")


@bp.route("/<tournament_url>/export-schedule")
@require_tournament_organizer("You must be a tournament organizer to export schedules")
def export_schedule(tournament_url):
    """Export schedule (tags, fields, matches) as TOML file download."""
    from app.services.schedule_import_export_service import ScheduleImportExportService
    from app.error_values import Ok, Err
    from flask import send_file
    import io

    res = ScheduleImportExportService.export_schedule(tournament_url)

    match res:
        case Ok(toml_content):
            # Create in-memory file
            file_obj = io.BytesIO(toml_content.encode("utf-8"))
            filename = f"{tournament_url}_schedule_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.toml"
            return send_file(
                file_obj,
                mimetype="application/toml",
                as_attachment=True,
                download_name=filename,
            )
        case Err(err):
            from app.utils.responses import json_error
            from app.utils.result_helpers import public_error_message

            return json_error(
                public_error_message(err),
                status_code=err.status_code if hasattr(err, "status_code") else 400,
            )


@bp.route("/<tournament_url>/import-schedule", methods=["POST"])
@require_tournament_organizer("You must be a tournament organizer to import schedules")
def import_schedule(tournament_url):
    """Import schedule from uploaded TOML file."""
    from app.services.schedule_import_export_service import ScheduleImportExportService
    from app.utils.result_helpers import json_from_result

    # Validate file upload
    if "schedule_file" not in request.files:
        return jsonify({"success": False, "error": "No file uploaded"}), 400

    file = request.files["schedule_file"]
    if file.filename == "":
        return jsonify({"success": False, "error": "No file selected"}), 400

    if not file.filename.endswith(".toml"):
        return jsonify({"success": False, "error": "File must be a .toml file"}), 400

    # Read file content
    try:
        toml_content = file.read().decode("utf-8")
    except UnicodeDecodeError:
        return (
            jsonify({"success": False, "error": "File must be valid UTF-8 text"}),
            400,
        )

    # Import schedule (all validation happens before any database changes)
    res = ScheduleImportExportService.import_schedule(tournament_url, toml_content)

    def result_to_payload(import_result):
        """Convert ImportResult to JSON payload."""
        return {
            "tags_created": import_result.tags_created,
            "tags_updated": import_result.tags_updated,
            "fields_created": import_result.fields_created,
            "fields_updated": import_result.fields_updated,
            "matches_created": import_result.matches_created,
            "matches_updated": import_result.matches_updated,
            "errors": import_result.errors,
        }

    return json_from_result(res, ok_to_payload=result_to_payload)


@bp.route("/<tournament_url>/register")
def tournament_register(tournament_url):
    """Tournament registration page."""
    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()
    if not tournament.registration_open:
        flash("Registration is not open for this tournament", "warning")
        return redirect(f"/{tournament_url}")

    team_registrations = TeamRegistration.query.filter_by(
        event=tournament_url, status=RegistrationStatus.CONFIRMED
    ).all()

    registered_teams = []
    for team_reg in team_registrations:
        team = Team.query.get(team_reg.team)
        if team:
            registered_teams.append({"team": team, "pseudonym": team_reg.pseudonym})

    return render_template(
        "tournament_register.html",
        tournament=tournament,
        registered_teams=registered_teams,
    )


@bp.route("/_api/camera-url")
@login_required
def camera_url_api():
    """Generate camera recording URL with access key. Requires TO access."""
    try:
        tournament_url = request.args.get("tournament")
        field_name = request.args.get("field")

        if not tournament_url or not field_name:
            return jsonify({"error": "Tournament and field parameters required"}), 400

        # Check if user is a TO for this tournament
        if is_not_TO(tournament_url):
            return (
                jsonify(
                    {"error": "Unauthorized: You must be a TO for this tournament"}
                ),
                403,
            )

        # Verify field exists
        field = Field.query.filter_by(event=tournament_url, name=field_name).first()
        if not field:
            return jsonify({"error": f'Field "{field_name}" not found'}), 404

        # Generate the camera URL with key
        access_key = generate_camera_key(tournament_url, field_name)
        from flask import url_for

        print(field_name)
        camera_url = url_for(
            "tournaments.record_page",
            tournament_url=tournament_url,
            field=field_name,
            camera_key=access_key,
            _external=True,
        )

        return jsonify({"url": camera_url})
    except Exception as e:
        import traceback

        print(f"Error in camera_url_api: {e}")
        print(traceback.format_exc())
        return jsonify({"error": f"Server error: {str(e)}"}), 500


@bp.route("/<tournament_url>/record")
def record_page(tournament_url):
    """Point recording page for a field."""
    # Validate camera access key
    field_name = request.args.get("field", "").strip()
    is_valid, error_response = require_camera_key(tournament_url, field_name)
    if not is_valid:
        return error_response[0], error_response[1]

    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()

    if not field_name:
        return (
            render_template(
                "record.html",
                tournament=tournament,
                field_name="",
                error="Field name is required",
            ),
            400,
        )

    # Verify field exists
    field = Field.query.filter_by(event=tournament_url, name=field_name).first()
    if not field:
        return (
            render_template(
                "record.html",
                tournament=tournament,
                field_name=field_name,
                error=f'Field "{field_name}" not found',
            ),
            404,
        )

    return render_template("record.html", tournament=tournament, field_name=field_name)


@bp.route("/_api/record/match-status")
def record_match_status():
    """Check if a field has an active match for point recording. No access key required."""
    from models import Point

    tournament_url = request.args.get("tournament")
    field_name = request.args.get("field")
    current_match_id = request.args.get(
        "current_match_id"
    )  # Optional: track specific match

    if not tournament_url or not field_name:
        return jsonify({"error": "Tournament and field parameters required"}), 400

    # Verify field exists
    field = Field.query.filter_by(event=tournament_url, name=field_name).first()
    if not field:
        return jsonify({"error": "Field not found"}), 404

    # Helper function to get points for a match
    def get_points_data(match):
        points = Point.query.filter_by(match=match.uuid).order_by(Point.stamp).all()
        points_data = []
        for p in points:
            # Ensure timestamps are sent as UTC with 'Z' suffix
            stamp_str = None
            end_stamp_str = None

            if p.stamp:
                # Convert to UTC if timezone-aware, or assume UTC if naive
                if p.stamp.tzinfo is None:
                    # Naive datetime - assume it's UTC
                    stamp_str = p.stamp.replace(tzinfo=timezone.utc).isoformat()
                else:
                    # Timezone-aware - convert to UTC
                    stamp_str = p.stamp.astimezone(timezone.utc).isoformat()
                # Ensure 'Z' suffix for UTC
                if not stamp_str.endswith("Z"):
                    stamp_str = stamp_str.replace("+00:00", "Z").replace("-00:00", "Z")
                    if not stamp_str.endswith("Z"):
                        stamp_str += "Z"

            if p.end_stamp:
                if p.end_stamp.tzinfo is None:
                    end_stamp_str = p.end_stamp.replace(tzinfo=timezone.utc).isoformat()
                else:
                    end_stamp_str = p.end_stamp.astimezone(timezone.utc).isoformat()
                if not end_stamp_str.endswith("Z"):
                    end_stamp_str = end_stamp_str.replace("+00:00", "Z").replace(
                        "-00:00", "Z"
                    )
                    if not end_stamp_str.endswith("Z"):
                        end_stamp_str += "Z"

            point_data = {
                "uuid": p.uuid,
                "stamp": stamp_str,
                "end_stamp": end_stamp_str,
            }
            points_data.append(point_data)
        return points_data

    # If we're tracking a specific match, check its status
    if current_match_id:
        match = Match.query.filter_by(
            uuid=current_match_id, event=tournament_url
        ).first()
        if match:
            # Continue recording if match is still IN_PROGRESS (not yet finalized)
            if match.status == MatchStatus.IN_PROGRESS:
                return jsonify(
                    {
                        "hasActiveMatch": True,
                        "match_id": match.uuid,
                        "match_name": match.name,
                        "start_time": (
                            match.confirmed_start_time.isoformat()
                            if match.confirmed_start_time
                            else None
                        ),
                        "status": match.status,
                        "points": get_points_data(match),
                    }
                )
            else:
                # Match is completed or in another state - stop recording
                return jsonify(
                    {
                        "hasActiveMatch": False,
                        "match_id": match.uuid,
                        "status": match.status,
                        "reason": "match_completed",
                    }
                )
        else:
            # Match not found - might have been deleted, stop recording
            return jsonify({"hasActiveMatch": False, "reason": "match_not_found"})

    # No specific match tracked - find any active match on this field
    match = Match.query.filter_by(
        event=tournament_url, field=field_name, status=MatchStatus.IN_PROGRESS
    ).first()

    if match:
        return jsonify(
            {
                "hasActiveMatch": True,
                "match_id": match.uuid,
                "match_name": match.name,
                "start_time": (
                    match.confirmed_start_time.isoformat()
                    if match.confirmed_start_time
                    else None
                ),
                "status": match.status,
                "points": get_points_data(match),
            }
        )
    else:
        return jsonify({"hasActiveMatch": False})


@bp.route("/_api/record/upload-chunk", methods=["POST"])
def record_upload_chunk():
    """Receive and store a video chunk for point recording. No access key required."""
    import os
    from flask import current_app
    from datetime import datetime
    import fcntl

    tournament_url = request.form.get("tournament")
    field_name = request.form.get("field")
    match_id = request.form.get("match_id")
    session_id = request.form.get("session_id")
    chunk_start_timestamp = request.form.get(
        "chunk_start_timestamp"
    )  # Absolute world time when chunk started
    start_timestamp = request.form.get("start_timestamp")
    recording_session_start_time = request.form.get("recording_session_start_time")
    chunk_duration = request.form.get("chunk_duration")  # Duration in milliseconds
    camera_name = request.form.get("camera_name")
    point_id = request.form.get("point_id")

    # Validate camera access key
    is_valid, error_response = require_camera_key(tournament_url, field_name)
    if not is_valid:
        return error_response[0], error_response[1]

    if not tournament_url or not field_name or not session_id or not match_id:
        return jsonify({"error": "Missing required parameters"}), 400

    # Verify field exists
    field = Field.query.filter_by(event=tournament_url, name=field_name).first()
    if not field:
        return jsonify({"error": "Field not found"}), 404

    if "chunk" not in request.files:
        return jsonify({"error": "No chunk file provided"}), 400

    chunk_file = request.files["chunk"]
    if chunk_file.filename == "":
        return jsonify({"error": "Empty chunk file"}), 400

    upload_dir = os.path.join(
        current_app.root_path,
        "../static/uploads/videos",
        tournament_url,
        field_name,
        match_id,
        camera_name,
    )
    os.makedirs(upload_dir, exist_ok=True)

    # Save chunk with index in filename for ordering
    chunk_index = len(
        list(filter(lambda x: not x.endswith(".json"), os.listdir(upload_dir)))
    )
    chunk_filename = f"chunk_{chunk_index}.webm"
    chunk_path = os.path.join(upload_dir, chunk_filename)
    chunk_file.save(chunk_path)

    # Debug: log saved chunk size and first 4 bytes (WebM/EBML magic is 1a 45 df a3)
    try:
        with open(chunk_path, "rb") as f:
            head = f.read(4)
        file_size = os.path.getsize(chunk_path)
        current_app.logger.info(
            "record chunk %s: size=%s bytes, first4=%s (EBML=%s)",
            chunk_index,
            file_size,
            head.hex() if len(head) == 4 else "short",
            head == b"\x1a\x45\xdf\xa3" if len(head) == 4 else False,
        )
    except Exception as e:
        current_app.logger.warning("record chunk debug read failed: %s", e)

    # Load or create chunks metadata with file locking to prevent race conditions
    chunks_meta_path = os.path.join(upload_dir, "chunks_meta.json")
    chunks_meta = {}

    # Use file locking to prevent concurrent write issues
    try:
        # Open file in read-write mode, create if it doesn't exist
        file_mode = "r+" if os.path.exists(chunks_meta_path) else "w+"
        with open(chunks_meta_path, file_mode) as lock_file:
            # Acquire exclusive lock
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except IOError:
                # If we can't get the lock immediately, wait for it
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)

            # Read existing metadata
            lock_file.seek(0)
            content = lock_file.read()
            if content.strip():
                try:
                    chunks_meta = json.loads(content)
                except (json.JSONDecodeError, ValueError):
                    chunks_meta = {}

            # Store chunk metadata
            chunk_meta = {
                "filename": chunk_filename,
                "session_id": session_id,
                "chunk_start_timestamp": (
                    float(chunk_start_timestamp)
                ),  # Absolute world time in milliseconds
                "chunk_duration": (float(chunk_duration)),  # Duration in milliseconds
                "point_id": point_id,
                "camera_name": camera_name,
                "recording_session_start_time": (float(recording_session_start_time)),
            }
            chunks_meta[str(chunk_index)] = chunk_meta  # Use string key for consistency

            # Write metadata back
            lock_file.seek(0)
            lock_file.truncate(0)
            json.dump(chunks_meta, lock_file, indent=2)
            lock_file.flush()
            # Lock is released when file is closed
    except (IOError, OSError) as e:
        print("error writing :sob:")

    return jsonify(
        {"success": True, "chunk_index": chunk_index, "session_id": session_id}
    )


@bp.route("/_api/record/finalize", methods=["POST"])
def record_finalize():
    data = request.json
    tournament_url = data.get("tournament")
    field_name = data.get("field")
    match_id = data.get("match_id")
    camera_name = data.get("camera_name")

    # Validate camera access key
    is_valid, error_response = require_camera_key(tournament_url, field_name)
    if not is_valid:
        return error_response[0], error_response[1]

    if not tournament_url or not field_name or not match_id or not camera_name:
        return jsonify({"error": "Missing required parameters"}), 400

    # Verify field exists
    if not Field.query.filter_by(event=tournament_url, name=field_name).first():
        return jsonify({"error": "Field not found"}), 404

    # Directory where chunks are stored (same layout as upload-chunk: tournament/field/match_id/camera_name)
    chunk_dir = path.join(
        current_app.root_path,
        "../static/uploads/videos",
        tournament_url,
        field_name,
        match_id,
        camera_name,
    )
    if not path.exists(chunk_dir):
        return jsonify({"error": "Recording directory not found"}), 404

    _ = executor.submit(
        finalize_recording_worker,
        current_app.logger,
        tournament_url,
        field_name,
        match_id,
        camera_name,
        chunk_dir,
    )

    # For now, just return success
    return jsonify(
        {
            "success": True,
            "message": "all recordings uploaded; processing has begun",
            "match_id": match_id,
        }
    )


@bp.route("/<tournament_url>/update-settings", methods=["POST"])
@login_required
def update_tournament_settings(tournament_url):
    """Update tournament settings."""
    if is_not_TO(tournament_url):
        return redirect(f"/{tournament_url}")

    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()

    tournament.name = request.form["name"]
    tournament.location = request.form.get("location", "")
    tournament.num_fields = int(request.form.get("num_fields", 1))
    tournament.n_max_teams = int(request.form.get("n_max_teams", 0) or 0) or None
    tournament.max_team_size_roster = (
        int(request.form.get("max_team_size_roster", 0) or 0) or None
    )
    tournament.max_team_size_field = (
        int(request.form.get("max_team_size_field", 0) or 0) or None
    )
    tournament.team_reg_fee = float(request.form.get("team_reg_fee", 0))
    tournament.player_reg_fee = float(request.form.get("player_reg_fee", 0))
    tournament.about = request.form.get("about", "")
    tournament.terms_link = request.form.get("terms_link", "")
    tournament.head_refs_allowed_list = request.form.get("head_refs_allowed_list", "")
    tournament.head_refs_allow_reffing_teams = (
        "head_refs_allow_reffing_teams" in request.form
    )
    tournament.head_refs_allow_anyone = "head_refs_allow_anyone" in request.form
    tournament.published = "published" in request.form
    tournament.schedule_published = "schedule_published" in request.form
    tournament.registration_open = "registration_open" in request.form

    if request.form.get("start_date"):
        tournament.start_date = datetime.strptime(
            request.form["start_date"], "%Y-%m-%d"
        )

    if request.form.get("end_date"):
        tournament.end_date = datetime.strptime(request.form["end_date"], "%Y-%m-%d")
    else:
        tournament.end_date = None

    db.session.commit()
    flash("Tournament settings updated successfully!", "success")
    return redirect(f"/{tournament_url}/settings")


@bp.route("/<tournament_url>/add-match", methods=["POST"])
@login_required
def add_match(tournament_url):
    """Add a match to tournament."""
    if is_not_TO(tournament_url):
        return redirect(f"/{tournament_url}")

    # Check if BREAK or JOIN is selected from the Match Type dropdown (renamed from 'dynamic')
    match_type_value = request.form.get("dynamic", "")

    if match_type_value == ScheduleType.BREAK:
        schedule_type = ScheduleType.BREAK
        set_type = SetType.SETS  # Not used for BREAK, but set a default
        nominal_length = int(request.form.get("length", 60))
    elif match_type_value == ScheduleType.JOIN:
        schedule_type = ScheduleType.JOIN
        set_type = SetType.SETS  # Not used for JOIN, but set a default
        nominal_length = 0
    else:
        if match_type_value == ScheduleType.SAFE:
            schedule_type = ScheduleType.SAFE
        elif match_type_value == ScheduleType.FAST:
            schedule_type = ScheduleType.FAST
        else:
            schedule_type = ScheduleType.STATIC
        set_type = request.form.get("match_type", SetType.SETS)
        nominal_length = int(request.form.get("length", 60))

    # BREAK and JOIN matches don't have teams/refs
    if schedule_type in (ScheduleType.BREAK, ScheduleType.JOIN):
        team1_id = None
        team1_name = ""
        team2_id = None
        team2_name = ""
        refs_initial = ""
    else:
        team1_name = request.form.get("team1", "")
        team2_name = request.form.get("team2", "")
        team1_id, _ = resolve_team_name_to_id(team1_name, tournament_url)
        team2_id, _ = resolve_team_name_to_id(team2_name, tournament_url)
        refs_initial = request.form.get("refs", "")

    ribbon = request.form.get("ribbon", "") == "on"  # Checkbox value

    # Validate match name doesn't contain "::"
    match_name = request.form["match_name"]
    if "::" in match_name:
        flash('Match names cannot contain "::"', "error")
        return redirect(f"/{tournament_url}/setup")

    # Validate match name uniqueness
    # BREAK and JOIN matches can have duplicate names on different fields
    # Other matches must have unique names within the tournament
    match_field = request.form.get("field", "")
    if schedule_type in (ScheduleType.BREAK, ScheduleType.JOIN):
        # For BREAK/JOIN: check uniqueness by (name, event, field)
        existing_match = Match.query.filter_by(
            event=tournament_url,
            name=match_name,
            field=match_field,
            schedule_type=schedule_type,
        ).first()
        if existing_match:
            flash(
                f'A {schedule_type} match with the name "{match_name}" already exists on field "{match_field}" in this tournament',
                "error",
            )
            return redirect(f"/{tournament_url}/setup")
    else:
        # For other matches: check uniqueness by (name, event)
        existing_match = Match.query.filter_by(
            event=tournament_url, name=match_name
        ).first()
        if existing_match:
            flash(
                f'A match with the name "{match_name}" already exists in this tournament',
                "error",
            )
            return redirect(f"/{tournament_url}/setup")

    # Get stones_per_set for STONES matches (with fallback to deprecated nstonesperset for backward compatibility)
    stones_per_set_value = None
    if set_type == SetType.STONES:
        stones_per_set_str = request.form.get("stones_per_set") or request.form.get(
            "nstonesperset"
        )
        if stones_per_set_str:
            try:
                stones_per_set_value = int(stones_per_set_str)
            except (ValueError, TypeError):
                stones_per_set_value = None

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

    # For new matches, populate explicit team IDs from _initial fields
    # Tag references are resolved by querying the Tag table, match references by apply_match_dependencies
    final_team1 = None
    if team1_id:
        final_team1 = team1_id
    elif team1_name:
        if is_explicit_team_id(team1_name):
            final_team1 = team1_name
        else:
            # Try to resolve as tag reference
            resolved_team = resolve_tag_to_team(team1_name, tournament_url)
            if resolved_team:
                final_team1 = resolved_team

    final_team2 = None
    if team2_id:
        final_team2 = team2_id
    elif team2_name:
        if is_explicit_team_id(team2_name):
            final_team2 = team2_name
        else:
            # Try to resolve as tag reference
            resolved_team = resolve_tag_to_team(team2_name, tournament_url)
            if resolved_team:
                final_team2 = resolved_team

    # For refs, populate explicit team IDs and resolve tag references maintaining index structure
    final_refs = None
    if refs_initial:
        refs_initial_list = [r.strip() for r in refs_initial.split(",")]
        refs_list = [""] * len(refs_initial_list)
        has_explicit_ids = False
        for i, initial_ref in enumerate(refs_initial_list):
            if initial_ref:
                if is_explicit_team_id(initial_ref):
                    refs_list[i] = initial_ref
                    has_explicit_ids = True
                else:
                    # Try to resolve as tag reference
                    resolved_team = resolve_tag_to_team(initial_ref, tournament_url)
                    if resolved_team:
                        refs_list[i] = resolved_team
                        has_explicit_ids = True
        if has_explicit_ids:
            final_refs = ", ".join(refs_list)

    # Skip condition only for SAFE and FAST; clear for STATIC, BREAK, and JOIN
    skip_condition_raw = request.form.get("skip_condition", "").strip() or None
    skip_condition = (
        skip_condition_raw
        if schedule_type in (ScheduleType.SAFE, ScheduleType.FAST)
        else None
    )

    match = Match(
        name=match_name,
        event=tournament_url,
        field=request.form.get("field", ""),
        team1=final_team1,
        team1_initial=team1_name,
        team2=final_team2,
        team2_initial=team2_name,
        schedule_type=schedule_type,
        set_type=set_type,
        ribbon=ribbon,
        nsets=(
            int(request.form.get("nsets", 3))
            if schedule_type not in (ScheduleType.BREAK, ScheduleType.JOIN)
            else None
        ),
        nominal_length=nominal_length,
        refs=final_refs,
        refs_initial=refs_initial,
        stones_per_set=stones_per_set_value,
        skip_condition=skip_condition,
    )

    db.session.add(match)
    db.session.flush()  # Flush to get UUID before updating links

    # For dynamic matches, set previous_match from form and compute start time from it
    # For static matches, use the provided start_time
    if schedule_type != ScheduleType.STATIC:
        # Get previous_match from form
        prev_match_id = request.form.get("previous_match", "")
        if prev_match_id:
            # Update doubly linked list: insert this match after prev_match
            update_match_previous_link(
                match, prev_match_id, tournament_url, is_new=True
            )
        else:
            match.previous_match = None
        match.nominal_start_time = compute_dynamic_match_nominal_start_time(
            match, tournament_url
        )
    else:
        # Static matches can have manual start time
        # Prefer UTC ISO format from client conversion, fallback to datetime-local (assumed server-local)
        if request.form.get("start_time_utc"):
            # Client sent UTC ISO string
            from app.utils.datetime_helpers import to_aware_utc

            utc_str = request.form["start_time_utc"]
            try:
                dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
                match.nominal_start_time = dt.replace(tzinfo=None)  # Store as naive UTC
            except (ValueError, AttributeError):
                # Fallback to old format
                if request.form.get("start_time"):
                    from app.utils.datetime_helpers import parse_datetime_local_to_utc

                    match.nominal_start_time = parse_datetime_local_to_utc(
                        request.form["start_time"]
                    )
        elif request.form.get("start_time"):
            # Old format: datetime-local (assumed server-local), convert to UTC
            from app.utils.datetime_helpers import parse_datetime_local_to_utc

            match.nominal_start_time = parse_datetime_local_to_utc(
                request.form["start_time"]
            )

    # Set initial status: STATIC matches are READY_TO_START, others are NOT_STARTED
    if schedule_type == ScheduleType.STATIC:
        match.status = MatchStatus.READY_TO_START
    else:
        match.status = MatchStatus.NOT_STARTED

    # Validate inputs and constraints (after start time is computed)
    ok, err = validate_match_input(match, tournament_url)
    if not ok:
        db.session.rollback()
        flash(err, "error")
        return redirect(f"/{tournament_url}/setup")

    db.session.commit()

    try:
        recompute_all_match_times(tournament_url)
    except Exception:
        pass

    flash("Match added successfully!", "success")
    return redirect(f"/{tournament_url}/setup")


@bp.route("/<tournament_url>/add-field", methods=["POST"])
@login_required
def add_field(tournament_url):
    """Add a field to tournament."""
    if is_not_TO(tournament_url):
        return redirect(f"/{tournament_url}")

    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()

    # Get camera URLs from form (camera[] array)
    camera_urls = request.form.getlist("camera[]")
    # Filter out empty values
    camera_urls = [url.strip() for url in camera_urls if url.strip()]

    # Store as JSON array
    camera_value = json.dumps(camera_urls) if camera_urls else ""

    field = Field(
        event=tournament_url, name=request.form["field_name"], camera=camera_value
    )

    db.session.add(field)
    db.session.commit()

    current_field_count = Field.query.filter_by(event=tournament_url).count()
    if current_field_count >= tournament.num_fields:
        flash(f"Maximum number of fields ({tournament.num_fields}) reached", "error")
        return redirect(f"/{tournament_url}/setup")

    flash("Field added successfully!", "success")
    return redirect(f"/{tournament_url}/setup")


@bp.route("/<tournament_url>/edit-field")
@login_required
def edit_field(tournament_url):
    """Edit field page."""
    if is_not_TO(tournament_url):
        return redirect(f"/{tournament_url}")

    field_id = request.args.get("id")
    if not field_id:
        flash("Field ID is required", "error")
        return redirect(f"/{tournament_url}/setup")

    field = Field.query.get_or_404(field_id)
    return render_template(
        "edit_field.html", tournament_url=tournament_url, field=field
    )


@bp.route("/<tournament_url>/update-field", methods=["POST"])
@login_required
def update_field(tournament_url):
    """Update field."""
    if is_not_TO(tournament_url):
        return redirect(f"/{tournament_url}")

    field_id = request.form.get("field_id")
    if not field_id:
        flash("Field ID is required", "error")
        return redirect(f"/{tournament_url}/setup")

    field = Field.query.get_or_404(field_id)
    old_field_name = field.name
    new_field_name = request.form["field_name"]

    # Update field name
    field.name = new_field_name

    # Get camera URLs from form (camera[] array)
    camera_urls = request.form.getlist("camera[]")
    # Filter out empty values
    camera_urls = [url.strip() for url in camera_urls if url.strip()]

    # Get old camera URLs for comparison
    old_camera_urls = []
    if field.camera:
        from app.utils.camera_helpers import parse_camera_urls

        old_camera_urls = parse_camera_urls(field.camera)

    # Store as JSON array
    field.camera = json.dumps(camera_urls) if camera_urls else ""

    # Get all matches that reference this field (for both name and camera updates)
    # Use old field name if name changed, otherwise use current name
    field_name_for_query = (
        old_field_name if old_field_name != new_field_name else new_field_name
    )
    matches_to_update = Match.query.filter_by(
        event=tournament_url, field=field_name_for_query
    ).all()

    # If camera URLs changed, update matches and points that reference this field
    camera_urls_changed = old_camera_urls != camera_urls
    camera_update_count = 0
    if camera_urls_changed:
        # Build mapping from old index to new index based on URL matching
        # This handles reordering, additions, and removals
        old_to_new_index_map = {}
        for new_idx, new_url in enumerate(camera_urls):
            # Find if this URL existed in old list
            try:
                old_idx = old_camera_urls.index(new_url)
                old_to_new_index_map[str(old_idx)] = str(new_idx)
            except ValueError:
                # New URL, no mapping needed
                pass

        # Update matches that reference this field
        for match in matches_to_update:
            if match.camera_stream_starts:
                try:
                    stream_starts = json.loads(match.camera_stream_starts)
                    # Remap camera indices
                    new_stream_starts = {}
                    for old_idx_str, start_time in stream_starts.items():
                        if old_idx_str in old_to_new_index_map:
                            new_idx_str = old_to_new_index_map[old_idx_str]
                            new_stream_starts[new_idx_str] = start_time
                        # If old index not in map, camera was removed - don't include it
                    match.camera_stream_starts = (
                        json.dumps(new_stream_starts) if new_stream_starts else None
                    )
                    camera_update_count += 1
                except (json.JSONDecodeError, TypeError) as e:
                    print(
                        f"Error updating camera_stream_starts for match {match.uuid}: {e}"
                    )
                    # If parsing fails, clear it
                    match.camera_stream_starts = None

        # Update points that reference this field (via the match)
        # Get all points for matches on this field
        from models import Point
        from app.utils.camera_helpers import calculate_stream_timestamp

        point_update_count = 0
        for match in matches_to_update:
            points = Point.query.filter_by(match=match.uuid).all()

            # Get stream start times for this match
            stream_starts = {}
            if match.camera_stream_starts:
                try:
                    stream_starts = json.loads(match.camera_stream_starts)
                except (json.JSONDecodeError, TypeError):
                    pass

            for point in points:
                # First, handle camera_index remapping if needed
                if point.camera_index is not None:
                    old_idx_str = str(point.camera_index)
                    if old_idx_str in old_to_new_index_map:
                        # Remap to new index
                        new_idx = int(old_to_new_index_map[old_idx_str])
                        point.camera_index = new_idx
                        point_update_count += 1
                    else:
                        # Camera at this index was removed - try to find matching URL
                        # If we can't find it, set to None
                        if point.camera_index < len(old_camera_urls):
                            old_url = old_camera_urls[point.camera_index]
                            try:
                                new_idx = camera_urls.index(old_url)
                                point.camera_index = new_idx
                                point_update_count += 1
                            except ValueError:
                                # URL not found in new list, set to None
                                point.camera_index = None
                                point.stream_timestamp = None
                                point_update_count += 1
                        else:
                            # Index was out of bounds, set to None
                            point.camera_index = None
                            point.stream_timestamp = None
                            point_update_count += 1

                # Recompute stream_timestamp for all points that have a camera_index and stamp
                # This ensures timestamps are recalculated based on current stream start times
                if point.camera_index is not None and point.stamp:
                    camera_idx_str = str(point.camera_index)
                    if camera_idx_str in stream_starts:
                        stream_start_time = stream_starts[camera_idx_str]
                        new_timestamp = calculate_stream_timestamp(
                            point.stamp, stream_start_time
                        )
                        if new_timestamp is not None:
                            point.stream_timestamp = new_timestamp
                            point_update_count += 1

    # Propagate field name change to all matches that reference this field
    name_update_count = 0
    if old_field_name != new_field_name:
        for match in matches_to_update:
            match.field = new_field_name
            name_update_count += 1

    # Generate success message
    update_messages = []
    if name_update_count > 0:
        update_messages.append(
            f"Updated {name_update_count} match(es) to use the new field name"
        )
    if camera_urls_changed:
        if camera_update_count > 0:
            update_messages.append(
                f"Updated camera stream data for {camera_update_count} match(es)"
            )
        if point_update_count > 0:
            update_messages.append(
                f"Updated camera indices for {point_update_count} point(s)"
            )

    if update_messages:
        flash(f'Field updated successfully! {" ".join(update_messages)}.', "success")
    else:
        flash("Field updated successfully!", "success")

    db.session.commit()
    return redirect(f"/{tournament_url}/setup")


@bp.route("/<tournament_url>/delete-field", methods=["POST"])
@login_required
def delete_field(tournament_url):
    """Delete field."""
    if is_not_TO(tournament_url):
        return redirect(f"/{tournament_url}")

    field_id = request.form.get("field_id")
    if not field_id:
        flash("Field ID is required", "error")
        return redirect(f"/{tournament_url}/setup")

    field = Field.query.get_or_404(field_id)
    db.session.delete(field)
    db.session.commit()
    flash("Field deleted successfully!", "success")
    return redirect(f"/{tournament_url}/setup")


@bp.route("/<tournament_url>/add-tag", methods=["POST"])
@login_required
def add_tag(tournament_url):
    """Add a tag to tournament."""
    if is_not_TO(tournament_url):
        return redirect(f"/{tournament_url}")

    tag = Tag(event=tournament_url, name=request.form["tag_name"])

    db.session.add(tag)
    db.session.commit()

    flash("Tag added successfully!", "success")
    return redirect(f"/{tournament_url}/setup")


@bp.route("/<tournament_url>/edit-tag")
@login_required
def edit_tag(tournament_url):
    """Edit tag page."""
    if is_not_TO(tournament_url):
        return redirect(f"/{tournament_url}")

    tag_id = request.args.get("id")
    if not tag_id:
        flash("Tag ID is required", "error")
        return redirect(f"/{tournament_url}/setup")

    tag = Tag.query.get_or_404(tag_id)
    return render_template("edit_tag.html", tournament_url=tournament_url, tag=tag)


@bp.route("/<tournament_url>/update-tag", methods=["POST"])
@login_required
def update_tag(tournament_url):
    """Update tag."""
    if is_not_TO(tournament_url):
        return redirect(f"/{tournament_url}")

    tag_id = request.form.get("tag_id")
    if not tag_id:
        flash("Tag ID is required", "error")
        return redirect(f"/{tournament_url}/setup")

    tag = Tag.query.get_or_404(tag_id)
    tag.name = request.form["tag_name"]

    db.session.commit()
    flash("Tag updated successfully!", "success")
    return redirect(f"/{tournament_url}/setup")


@bp.route("/<tournament_url>/delete-tag", methods=["POST"])
@login_required
def delete_tag(tournament_url):
    """Delete tag."""
    if is_not_TO(tournament_url):
        return redirect(f"/{tournament_url}")

    tag_id = request.form.get("tag_id")
    if not tag_id:
        flash("Tag ID is required", "error")
        return redirect(f"/{tournament_url}/setup")

    tag = Tag.query.get_or_404(tag_id)
    db.session.delete(tag)
    db.session.commit()
    flash("Tag deleted successfully!", "success")
    return redirect(f"/{tournament_url}/setup")


@bp.route("/<tournament_url>/edit-match")
@login_required
def edit_match(tournament_url):
    """Edit match page."""
    if is_not_TO(tournament_url):
        return redirect(f"/{tournament_url}")

    match_id = request.args.get("id")
    if not match_id:
        flash("Match ID is required", "error")
        return redirect(f"/{tournament_url}/setup")

    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()
    match = Match.query.get_or_404(match_id)
    matches = (
        Match.query.filter_by(event=tournament_url)
        .order_by(Match.nominal_start_time)
        .all()
    )
    fields = Field.query.filter_by(event=tournament_url).all()
    tags = Tag.query.filter_by(event=tournament_url).all()
    return render_template(
        "edit_match.html",
        tournament=tournament,
        match=match,
        matches=matches,
        fields=fields,
        tags=tags,
    )


@bp.route("/<tournament_url>/update-match", methods=["POST"])
@login_required
def update_match(tournament_url):
    """Update match."""
    if is_not_TO(tournament_url):
        return redirect(f"/{tournament_url}")

    match_id = request.form.get("match_id")
    if not match_id:
        flash("Match ID is required", "error")
        return redirect(f"/{tournament_url}/setup")

    match = Match.query.get_or_404(match_id)
    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()

    # Check if BREAK or JOIN is selected from the Match Type dropdown (renamed from 'dynamic')
    match_type_value = request.form.get("dynamic", "")

    if match_type_value == ScheduleType.BREAK:
        schedule_type = ScheduleType.BREAK
        set_type = match.set_type  # Keep existing set_type
    elif match_type_value == ScheduleType.JOIN:
        schedule_type = ScheduleType.JOIN
        set_type = match.set_type  # Keep existing set_type
    else:
        if match_type_value == ScheduleType.SAFE:
            schedule_type = ScheduleType.SAFE
        elif match_type_value == ScheduleType.FAST:
            schedule_type = ScheduleType.FAST
        else:
            schedule_type = ScheduleType.STATIC
        set_type = request.form.get("match_type", match.set_type)

    # BREAK and JOIN matches don't have teams/refs
    if schedule_type in (ScheduleType.BREAK, ScheduleType.JOIN):
        team1_id = None
        team1_name = ""
        team2_id = None
        team2_name = ""
        refs_initial = ""
    else:
        team1_name = request.form.get("team1", "")
        team2_name = request.form.get("team2", "")
        team1_id, _ = resolve_team_name_to_id(team1_name, tournament_url)
        team2_id, _ = resolve_team_name_to_id(team2_name, tournament_url)
        refs_initial = request.form.get("refs", "")

    # Validate match name doesn't contain "::"
    new_match_name = request.form.get("match_name", match.name)
    if "::" in new_match_name:
        flash('Match names cannot contain "::"', "error")
        return redirect(f"/{tournament_url}/setup")

    # Validate match name uniqueness (excluding current match)
    # BREAK and JOIN matches can have duplicate names on different fields
    # Other matches must have unique names within the tournament
    new_match_field = request.form.get("field", match.field or "")
    if new_match_name != match.name or new_match_field != (match.field or ""):
        if schedule_type in (ScheduleType.BREAK, ScheduleType.JOIN):
            # For BREAK/JOIN: check uniqueness by (name, event, field)
            existing_match = Match.query.filter_by(
                event=tournament_url,
                name=new_match_name,
                field=new_match_field,
                schedule_type=schedule_type,
            ).first()
            if existing_match and existing_match.uuid != match.uuid:
                flash(
                    f'A {schedule_type} match with the name "{new_match_name}" already exists on field "{new_match_field}" in this tournament',
                    "error",
                )
                return redirect(f"/{tournament_url}/setup")
        else:
            # For other matches: check uniqueness by (name, event)
            existing_match = Match.query.filter_by(
                event=tournament_url, name=new_match_name
            ).first()
            if existing_match and existing_match.uuid != match.uuid:
                flash(
                    f'A match with the name "{new_match_name}" already exists in this tournament',
                    "error",
                )
                return redirect(f"/{tournament_url}/setup")

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

    match.name = new_match_name
    match.field = request.form.get("field", "")

    # Handle team1_initial changes
    old_team1_initial = match.team1_initial or ""
    match.team1_initial = team1_name
    if old_team1_initial != team1_name:
        # Clear team1, but populate if explicit team ID or resolved tag
        if team1_id:
            match.team1 = team1_id
        elif is_explicit_team_id(team1_name):
            match.team1 = team1_name
        else:
            # Try to resolve as tag reference
            resolved_team = resolve_tag_to_team(team1_name, tournament_url)
            match.team1 = resolved_team if resolved_team else None
    else:
        # If team1_initial didn't change, only update team1 if we have an explicit team_id or can resolve tag
        if team1_id:
            match.team1 = team1_id
        elif not match.team1 and team1_name:
            # Try to resolve tag if team1 is not set
            resolved_team = resolve_tag_to_team(team1_name, tournament_url)
            if resolved_team:
                match.team1 = resolved_team

    # Handle team2_initial changes
    old_team2_initial = match.team2_initial or ""
    match.team2_initial = team2_name
    if old_team2_initial != team2_name:
        # Clear team2, but populate if explicit team ID or resolved tag
        if team2_id:
            match.team2 = team2_id
        elif is_explicit_team_id(team2_name):
            match.team2 = team2_name
        else:
            # Try to resolve as tag reference
            resolved_team = resolve_tag_to_team(team2_name, tournament_url)
            match.team2 = resolved_team if resolved_team else None
    else:
        # If team2_initial didn't change, only update team2 if we have an explicit team_id or can resolve tag
        if team2_id:
            match.team2 = team2_id
        elif not match.team2 and team2_name:
            # Try to resolve tag if team2 is not set
            resolved_team = resolve_tag_to_team(team2_name, tournament_url)
            if resolved_team:
                match.team2 = resolved_team

    match.schedule_type = schedule_type
    match.set_type = set_type
    match.ribbon = request.form.get("ribbon", "") == "on"  # Checkbox value

    # BREAK and JOIN don't have nsets
    if schedule_type not in (ScheduleType.BREAK, ScheduleType.JOIN):
        match.nsets = int(request.form.get("nsets", 3))
    else:
        match.nsets = None

    # Update stones_per_set for STONES matches (with fallback to deprecated nstonesperset for backward compatibility)
    if set_type == SetType.STONES:
        stones_per_set_str = request.form.get("stones_per_set") or request.form.get(
            "nstonesperset"
        )
        if stones_per_set_str:
            try:
                match.stones_per_set = int(stones_per_set_str)
            except (ValueError, TypeError):
                pass  # Keep existing value if invalid
        # If not provided and match doesn't have stones_per_set, try to migrate from nstonesperset
        elif match.nstonesperset and not match.stones_per_set:
            match.stones_per_set = match.nstonesperset
    else:
        # Clear stones_per_set for non-STONES matches
        match.stones_per_set = None

    # JOIN has zero length, BREAK can have length
    if schedule_type == ScheduleType.JOIN:
        match.nominal_length = 0
    elif schedule_type == ScheduleType.BREAK:
        match.nominal_length = int(
            request.form.get("length", match.nominal_length or 60)
        )
    else:
        match.nominal_length = int(
            request.form.get("length", match.nominal_length or 60)
        )

    # Update skip_condition (only for SAFE, FAST; clear for STATIC, BREAK, and JOIN)
    skip_condition_raw = request.form.get("skip_condition", "").strip() or None
    match.skip_condition = (
        skip_condition_raw
        if schedule_type in (ScheduleType.SAFE, ScheduleType.FAST)
        else None
    )

    # If refs_initial changed, clear refs and repopulate with explicit team IDs and resolved tag references
    old_refs_initial = match.refs_initial or ""
    match.refs_initial = refs_initial
    if old_refs_initial != refs_initial:
        # Clear refs, but populate any explicit team IDs and resolved tag references from refs_initial
        if refs_initial:
            refs_initial_list = [r.strip() for r in refs_initial.split(",")]
            refs_list = [""] * len(refs_initial_list)
            has_explicit_ids = False
            for i, initial_ref in enumerate(refs_initial_list):
                if initial_ref:
                    if is_explicit_team_id(initial_ref):
                        # Explicit team ID
                        refs_list[i] = initial_ref
                        has_explicit_ids = True
                    else:
                        # Try to resolve as tag reference
                        resolved_team = resolve_tag_to_team(initial_ref, tournament_url)
                        if resolved_team:
                            refs_list[i] = resolved_team
                            has_explicit_ids = True
            if has_explicit_ids:
                match.refs = ", ".join(refs_list)
            else:
                match.refs = None
        else:
            match.refs = None

    # For dynamic matches, set previous_match from form and compute start time from it
    # For static matches, ensure previous_match is cleared and use provided start_time
    if schedule_type != ScheduleType.STATIC:
        # Get previous_match from form
        prev_match_id = request.form.get("previous_match", "")
        if prev_match_id:
            # Update doubly linked list: insert this match after prev_match
            update_match_previous_link(
                match, prev_match_id, tournament_url, is_new=False
            )
        else:
            # Clear previous_match and update old previous's next_match if needed
            old_prev = match.previous_match
            match.previous_match = None
            if old_prev:
                old_prev_m = Match.query.filter_by(
                    uuid=old_prev, event=tournament_url
                ).first()
                if old_prev_m and old_prev_m.next_match == match.uuid:
                    old_prev_m.next_match = None
        match.nominal_start_time = compute_dynamic_match_nominal_start_time(
            match, tournament_url
        )
    else:
        # Static matches can have manual start time
        match.previous_match = None
        # Prefer UTC ISO format from client conversion, fallback to datetime-local (assumed server-local)
        if request.form.get("start_time_utc"):
            # Client sent UTC ISO string
            utc_str = request.form["start_time_utc"]
            try:
                dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
                match.nominal_start_time = dt.replace(tzinfo=None)  # Store as naive UTC
            except (ValueError, AttributeError):
                # Fallback to old format
                if request.form.get("start_time"):
                    from app.utils.datetime_helpers import parse_datetime_local_to_utc

                    match.nominal_start_time = parse_datetime_local_to_utc(
                        request.form["start_time"]
                    )
                else:
                    match.nominal_start_time = None
        elif request.form.get("start_time"):
            # Old format: datetime-local (assumed server-local), convert to UTC
            from app.utils.datetime_helpers import parse_datetime_local_to_utc

            match.nominal_start_time = parse_datetime_local_to_utc(
                request.form["start_time"]
            )
        else:
            match.nominal_start_time = None

    # Validate inputs and constraints
    ok, err = validate_match_input(match, tournament_url)
    if not ok:
        flash(err, "error")
        return redirect(f"/{tournament_url}/edit-match?id={match_id}")

    db.session.flush()  # Flush before updating sequence

    # Recompute all match times (for all dynamic matches that depend on this one)
    recompute_all_match_times(tournament_url)

    db.session.commit()
    flash("Match updated successfully!", "success")
    return redirect(f"/{tournament_url}/setup")


@bp.route("/<tournament_url>/update-tags", methods=["POST"])
@login_required
def update_tags(tournament_url):
    """Update tag team assignments. This updates the team column in the Tag table.
    All tag resolution will query the Tag table directly.
    """
    if is_not_TO(tournament_url):
        return redirect(f"/{tournament_url}")

    from models import Tag

    # Get all tags for this tournament
    tags = Tag.query.filter_by(event=tournament_url).all()

    # Update team column for each tag
    updated_count = 0
    for tag in tags:
        form_key = f"tag_{tag.id}"
        team_id = request.form.get(form_key, "").strip()
        if team_id:
            tag.team = team_id
            updated_count += 1
        else:
            # Clear team if no selection
            tag.team = None

    if updated_count == 0:
        flash("No tag conversions selected", "error")
        return redirect(f"/{tournament_url}/setup")

    db.session.commit()
    flash(f"Successfully updated {updated_count} tag(s)", "success")
    return redirect(f"/{tournament_url}/setup")


@bp.route("/<tournament_url>/update-all-references", methods=["POST"])
@login_required
def update_all_references(tournament_url):
    """Update all match references (winner/loser) for troubleshooting."""
    if is_not_TO(tournament_url):
        return redirect(f"/{tournament_url}")

    from app.utils.dependencies import apply_match_dependencies

    # Get all completed matches (have a winner; skipped matches are excluded)
    completed_matches = Match.query.filter_by(
        event=tournament_url, status=MatchStatus.COMPLETED
    ).all()

    updated_count = 0
    for match in completed_matches:
        if match.match_winner in ("TEAM1", "TEAM2"):
            try:
                apply_match_dependencies(tournament_url, match)
                updated_count += 1
            except Exception as e:
                print(f"Error updating references for match {match.name}: {e}")

    if updated_count > 0:
        flash(f"Updated references for {updated_count} completed matches", "success")
    else:
        flash("No references were updated", "info")

    return redirect(f"/{tournament_url}/setup")


@bp.route("/<tournament_url>/push-back-matches", methods=["POST"])
@login_required
def push_back_matches(tournament_url):
    """Push all non-started matches backwards by a specified amount of time (in minutes)."""
    if is_not_TO(tournament_url):
        return redirect(f"/{tournament_url}")

    try:
        minutes = int(request.form.get("minutes", 0))
    except (ValueError, TypeError):
        flash("Invalid number of minutes", "error")
        return redirect(f"/{tournament_url}/setup")

    non_started_matches = (
        Match.query.filter_by(event=tournament_url)
        .filter(
            ~Match.status.in_(
                [MatchStatus.IN_PROGRESS, MatchStatus.COMPLETED, MatchStatus.SKIPPED]
            )
        )
        .all()
    )

    updated_count = 0
    for match in non_started_matches:
        # Push back nominal_start_time if it exists
        if match.nominal_start_time:
            match.nominal_start_time = match.nominal_start_time + timedelta(
                minutes=minutes
            )
            updated_count += 1

        # Also push back confirmed_start_time if it exists (even when start time is already finalized)
        if match.confirmed_start_time:
            match.confirmed_start_time = match.confirmed_start_time + timedelta(
                minutes=minutes
            )

    db.session.commit()

    if updated_count > 0:
        flash(
            f"Pushed back {updated_count} non-started match(es) by {minutes} minute(s)",
            "success",
        )
    else:
        flash(
            "No matches were updated. All matches have already started or been completed.",
            "info",
        )

    return redirect(f"/{tournament_url}/setup")


@bp.route("/<tournament_url>/_api/autocomplete")
def tournament_autocomplete(tournament_url):
    """Autocomplete endpoint for tournament setup.
    Returns a list of suggestions with fields: type, value, label, id
    """
    q_raw = request.args.get("q", "")
    query = (q_raw or "").strip().lower()

    suggestions = []

    from app.domain.enums import RegistrationStatus

    # Teams registered in this tournament
    team_regs = TeamRegistration.query.filter_by(
        event=tournament_url, status=RegistrationStatus.CONFIRMED
    ).all()
    for reg in team_regs:
        pseudonym = (reg.pseudonym or "").strip()
        if not query or query in pseudonym.lower():
            suggestions.append(
                {
                    "type": "team",
                    "value": reg.team,  # Use team ID instead of pseudonym
                    "label": pseudonym,  # Display pseudonym in label
                    "id": reg.team,
                }
            )

    # Tags for this tournament (by name, surfaced as tag::TAG_NAME values)
    tags = (
        Tag.query.filter_by(event=tournament_url).all()
        if "Tag" in globals() or True
        else []
    )
    try:
        tags = Tag.query.filter_by(event=tournament_url).all()
    except Exception:
        tags = []
    for t in tags:
        name = (t.name or "").strip()
        if not query or query in name.lower():
            tag_ref = f"tag::{name}"
            suggestions.append(
                {"type": "tag", "value": tag_ref, "label": tag_ref, "id": t.id}
            )

    # Matches in this tournament (by name)
    # Exclude BREAK and JOIN matches entirely
    matches = (
        Match.query.filter_by(event=tournament_url)
        .filter(Match.schedule_type.notin_([ScheduleType.BREAK, ScheduleType.JOIN]))
        .all()
    )
    for m in matches:
        name = (m.name or "").strip()

        # Also offer winner/loser variants to help dynamic references (new format)
        winner_label = f"{name}::winner"
        loser_label = f"{name}::loser"
        if not query or query in winner_label.lower():
            suggestions.append(
                {
                    "type": "result",
                    "value": winner_label,
                    "label": winner_label,
                    "id": m.uuid,
                }
            )
        if not query or query in loser_label.lower():
            suggestions.append(
                {
                    "type": "result",
                    "value": loser_label,
                    "label": loser_label,
                    "id": m.uuid,
                }
            )

    # Limit and return
    # When query is empty, return all suggestions (for preloading)
    # When query is provided, limit to 50 for performance
    if not query:
        return jsonify(suggestions)
    else:
        return jsonify(suggestions[:50])


@bp.route("/<tournament_url>/_api/validate-dsl", methods=["POST"])
def validate_dsl(tournament_url):
    """Validate and simplify a DSL expression.
    Returns JSON with: valid (bool), value (the full interpreted value), simplified (str representation), error (str or None)
    """
    from flask import jsonify
    from app.utils.parser import (
        get_parser,
        DSLValidationError,
        Team,
        Match,
        SymbolicTeam,
        SymbolicMatch,
        Lambda,
    )

    def serialize_value(value):
        """Convert the interpreted value to a JSON-serializable format."""
        if isinstance(value, (int, bool, type(None))):
            return value
        elif isinstance(value, list):
            # Recursively serialize list elements
            return [serialize_value(item) for item in value]
        elif isinstance(value, Team):
            # Return team ID
            return {"type": "team", "id": value.obj.id}
        elif isinstance(value, Match):
            # Return match name
            return {"type": "match", "name": value.obj.name}
        elif isinstance(value, SymbolicTeam):
            # Return symbolic representation
            return {"type": "symbolic_team", "literal": value.literal}
        elif isinstance(value, SymbolicMatch):
            # Return symbolic representation
            return {"type": "symbolic_match", "literal": value.literal}
        elif isinstance(value, Lambda):
            # Lambda objects shouldn't appear in final results, but handle gracefully
            return {"type": "lambda", "params": value.params}
        else:
            # Fallback to string representation
            return str(value)

    def value_to_string(value):
        """Convert the interpreted value to a readable string representation."""
        if isinstance(value, (int, bool, type(None))):
            return str(value)
        elif isinstance(value, list):
            # Format as Lisp-like expression
            if len(value) > 0 and isinstance(value[0], str):
                # Preserved expression - format as s-expression
                return "(" + " ".join(value_to_string(item) for item in value) + ")"
            else:
                # Data list
                return "[" + ", ".join(value_to_string(item) for item in value) + "]"
        elif isinstance(value, Team):
            return f"[{value.obj.id}]"
        elif isinstance(value, Match):
            return f"{{{value.obj.name}}}"
        elif isinstance(value, SymbolicTeam):
            return f"[{value.literal}]"
        elif isinstance(value, SymbolicMatch):
            return f"{{{value.literal}}}"
        elif isinstance(value, Lambda):
            # Lambda objects shouldn't appear in final results, but handle gracefully
            params_str = " ".join(value.params) if value.params else ""
            return f"(lambda ({params_str}) ...)"
        else:
            return str(value)

    data = request.get_json()
    expression = data.get("expression", "").strip()

    if not expression:
        return jsonify(
            {"valid": True, "value": None, "simplified": None, "error": None}
        )

    try:
        parser = get_parser(tournament_url)
        result = parser.parse(expression)

        # Serialize the full value for JSON response
        serialized_value = serialize_value(result)

        # Create string representation
        simplified_str = value_to_string(result)

        # Only include simplified if it's different from the input
        simplified = simplified_str if simplified_str != expression else None

        return jsonify(
            {
                "valid": True,
                "value": serialized_value,
                "simplified": simplified,
                "error": None,
            }
        )
    except DSLValidationError as e:
        return jsonify(
            {"valid": False, "value": None, "simplified": None, "error": str(e)}
        )
    except Exception as e:
        return jsonify(
            {
                "valid": False,
                "value": None,
                "simplified": None,
                "error": f"Parse error: {str(e)}",
            }
        )


@bp.route("/<tournament_url>/delete", methods=["POST"])
@login_required
def delete_tournament(tournament_url):
    """Delete a tournament and all related data."""
    if is_not_TO(tournament_url):
        return redirect(f"/{tournament_url}")

    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()

    # Verify confirmation URL slug
    confirm_url = request.form.get("confirm_url", "").strip()
    if confirm_url != tournament_url:
        flash("Confirmation URL does not match. Tournament not deleted.", "error")
        return redirect(f"/{tournament_url}")

    # Import all necessary models
    from models import (
        Point,
        MatchNote,
        Match,
        HeadRef,
        PlayerRegistration,
        TeamRegistration,
        Field,
        Tag,
        SideComp,
        SideCompResult,
    )

    # Delete in order to respect foreign key constraints

    side_comps = SideComp.query.filter_by(event=tournament_url).all()
    side_comp_ids = [sc.id for sc in side_comps]
    if side_comp_ids:
        SideCompResult.query.filter(SideCompResult.comp.in_(side_comp_ids)).delete(
            synchronize_session=False
        )

    SideComp.query.filter_by(event=tournament_url).delete(synchronize_session=False)

    matches = Match.query.filter_by(event=tournament_url).all()
    match_uuids = [m.uuid for m in matches]
    if match_uuids:
        Point.query.filter(Point.match.in_(match_uuids)).delete(
            synchronize_session=False
        )
        MatchNote.query.filter(MatchNote.match.in_(match_uuids)).delete(
            synchronize_session=False
        )
    Match.query.filter_by(event=tournament_url).delete(synchronize_session=False)
    HeadRef.query.filter_by(event=tournament_url).delete(synchronize_session=False)
    PlayerRegistration.query.filter_by(event=tournament_url).delete(
        synchronize_session=False
    )
    TeamRegistration.query.filter_by(event=tournament_url).delete(
        synchronize_session=False
    )
    Field.query.filter_by(event=tournament_url).delete(synchronize_session=False)
    Tag.query.filter_by(event=tournament_url).delete(synchronize_session=False)
    TO.query.filter_by(event=tournament_url).delete(synchronize_session=False)
    db.session.delete(tournament)
    db.session.commit()

    flash(f'Tournament "{tournament.name}" has been permanently deleted.', "success")
    return redirect("/")


@bp.route("/<tournament_url>/add-to", methods=["POST"])
@login_required
def add_to(tournament_url):
    """Add a TO to the tournament."""

    if is_not_TO(tournament_url):
        return redirect(f"/{tournament_url}")

    user_id = request.form.get("user_id", "").strip()
    user_type = request.form.get("user_type", "").strip().lower()

    if not user_id or user_type not in ["player", "team"]:
        flash("Invalid user ID or type", "error")
        return redirect(f"/{tournament_url}/settings")

    # Verify the user exists
    from models import Player, Team

    if user_type == "player":
        user = Player.query.get(user_id)
        if not user:
            flash(f'Player with ID "{user_id}" not found', "error")
            return redirect(f"/{tournament_url}/settings")
    else:  # team
        user = Team.query.get(user_id)
        if not user:
            flash(f'Team with ID "{user_id}" not found', "error")
            return redirect(f"/{tournament_url}/settings")

    # Check if TO already exists
    existing_to = TO.query.filter_by(
        user_id=user_id, user_type=user_type, event=tournament_url
    ).first()

    if existing_to:
        flash(f"This user is already a TO for this tournament", "error")
        return redirect(f"/{tournament_url}/settings")

    # Create new TO entry
    new_to = TO(user_id=user_id, user_type=user_type, event=tournament_url)
    db.session.add(new_to)
    db.session.commit()

    user_name = user.name if user else user_id
    flash(f"Successfully added {user_name} as a TO", "success")
    return redirect(f"/{tournament_url}/settings")


@bp.route("/<tournament_url>/remove-to", methods=["POST"])
@login_required
def remove_to(tournament_url):
    """Remove a TO from the tournament."""

    if is_not_TO(tournament_url):
        return redirect(f"/{tournament_url}")

    to_id = request.form.get("to_id")
    if not to_id:
        flash("TO ID is required", "error")
        return redirect(f"/{tournament_url}/settings")

    # Get the TO entry to remove
    to_to_remove = TO.query.get_or_404(to_id)

    # Verify it's for this tournament
    if to_to_remove.event != tournament_url:
        flash("Invalid TO entry", "error")
        return redirect(f"/{tournament_url}/settings")

    # Prevent removing yourself (optional - you might want to allow this)
    if (
        to_to_remove.user_id == current_user.id
        and to_to_remove.user_type == current_user.__class__.__name__.lower()
    ):
        flash("You cannot remove yourself as a TO", "error")
        return redirect(f"/{tournament_url}/settings")

    # Get user info for flash message
    from models import Player, Team

    if to_to_remove.user_type == "player":
        user = Player.query.get(to_to_remove.user_id)
    else:
        user = Team.query.get(to_to_remove.user_id)
    user_name = user.name if user else to_to_remove.user_id

    # Delete the TO entry
    db.session.delete(to_to_remove)
    db.session.commit()

    flash(f"Successfully removed {user_name} as a TO", "success")
    return redirect(f"/{tournament_url}/settings")
