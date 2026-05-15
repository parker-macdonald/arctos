"""Tournament scheduling routes.

Recompute, import/export, add/update matches, push-back, autocomplete,
DSL validation. Part of the ``tournaments`` blueprint.
"""

from flask import (
    Blueprint,
    request,
    jsonify,
    current_app,
)
from flask_login import login_required, current_user
from flask_executor import Executor

from datetime import datetime, timedelta, timezone
import json
import time
import uuid

from models import (
    Tournament,
    Match,
    Field,
    Tag,
    Camera,
    Point,
    TeamRegistration,
    PlayerRegistration,
    Team,
    TO,
    League,
    db,
)
from app.services._common import current_user_type
from app.utils.helpers import (
    resolve_team_name_to_id,
    resolve_tag_to_team,
)
from app.utils.scheduling import (
    compute_dynamic_match_nominal_start_time,
    validate_match_input,
    recompute_all_match_times,
)
from app.utils.name_validation import match_name_char_error
from app.utils.decorators import require_tournament_organizer
from app.utils.datetime_helpers import now_utc_naive

from os import path, listdir

from app.utils.footage import finalize_recording_worker
from app.utils.user_uploads import (
    create_direct_user_upload_camera,
    list_batch_manifest_rows,
    register_batch_upload_completion,
)
from app.utils.camera_helpers import (
    generate_camera_key,
    require_camera_key,
)
from app.utils.recording_retry import (
    RETRY_FINALIZATION_USER_IDS_ENV,
    current_user_can_retry_finalization,
)
from app.utils import preview_store

from app.domain.enums import (
    MatchStatus,
    ScheduleType,
    SetType,
)
from app.services.registration_resolver import is_player_registered
from app.services.permission_service import PermissionService

from . import bp


@bp.route("/<tournament_url>/recompute-schedule", methods=["POST"])
@require_tournament_organizer("Only tournament organizers can access this page")
def recompute_schedule(tournament_url):
    """Force full recompute of match times as if a match were just edited (TO only)."""
    try:
        recompute_all_match_times(tournament_url)
        return (
            jsonify({"success": True, "message": "Schedule recomputed successfully."}),
            200,
        )
    except Exception as e:
        return jsonify({"success": False, "error": f"Recompute failed: {e}"}), 500


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


@bp.route("/<tournament_url>/add-match", methods=["POST"])
@require_tournament_organizer("Only tournament organizers can access this page")
def add_match(tournament_url):
    """Add a match to tournament."""
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

    match_name = request.form["match_name"]
    mn_err = match_name_char_error(match_name)
    if mn_err:
        return jsonify({"success": False, "error": mn_err}), 400

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
            return (
                jsonify(
                    {
                        "success": False,
                        "error": f'A {schedule_type} match with the name "{match_name}" already exists on field "{match_field}" in this tournament',
                    }
                ),
                400,
            )
    else:
        # For other matches: check uniqueness by (name, event)
        existing_match = Match.query.filter_by(event=tournament_url, name=match_name).first()
        if existing_match:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": f'A match with the name "{match_name}" already exists in this tournament',
                    }
                ),
                400,
            )

    stones_per_set_value = None
    if set_type == SetType.STONES:
        stones_per_set_str = request.form.get("stones_per_set")
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

    # For refs, populate explicit team IDs and resolve tag references maintaining index structure.
    # The ref slot rows are inserted after the match has been flushed so they can reference its uuid.
    refs_resolved_csv: str | None = None
    if refs_initial:
        refs_initial_list = [r.strip() for r in refs_initial.split(",")]
        refs_list = [""] * len(refs_initial_list)
        for i, initial_ref in enumerate(refs_initial_list):
            if not initial_ref:
                continue
            if is_explicit_team_id(initial_ref):
                refs_list[i] = initial_ref
            else:
                resolved_team = resolve_tag_to_team(initial_ref, tournament_url)
                if resolved_team:
                    refs_list[i] = resolved_team
        refs_resolved_csv = ",".join(refs_list)

    # Skip condition only for SAFE and FAST; clear for STATIC, BREAK, and JOIN
    skip_condition_raw = request.form.get("skip_condition", "").strip() or None
    skip_condition = skip_condition_raw if schedule_type in (ScheduleType.SAFE, ScheduleType.FAST) else None

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
            int(request.form.get("nsets", 3)) if schedule_type not in (ScheduleType.BREAK, ScheduleType.JOIN) else None
        ),
        nominal_length=nominal_length,
        stones_per_set=stones_per_set_value,
        skip_condition=skip_condition,
    )

    db.session.add(match)
    db.session.flush()  # Flush to get UUID before updating links

    if refs_initial:
        from app.services.dual_write import set_match_referees_from_csv

        set_match_referees_from_csv(match, refs_resolved_csv, refs_initial)

    # For dynamic matches, set previous_match from form and compute start time from it
    # For static matches, use the provided start_time
    if schedule_type != ScheduleType.STATIC:
        # Get previous_match from form
        prev_match_id = request.form.get("previous_match", "")
        if prev_match_id:
            # Update doubly linked list: insert this match after prev_match
            update_match_previous_link(match, prev_match_id, tournament_url, is_new=True)
        else:
            match.previous_match = None
        match.nominal_start_time = compute_dynamic_match_nominal_start_time(match, tournament_url)
    else:
        # Static matches can have manual start time
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

                    match.nominal_start_time = parse_datetime_local_to_utc(request.form["start_time"])
        elif request.form.get("start_time"):
            # Old format: datetime-local (assumed server-local), convert to UTC
            from app.utils.datetime_helpers import parse_datetime_local_to_utc

            match.nominal_start_time = parse_datetime_local_to_utc(request.form["start_time"])

    # Set initial status: STATIC matches are TIME_FINALIZED, others are NOT_STARTED
    if schedule_type == ScheduleType.STATIC:
        match.status = MatchStatus.TIME_FINALIZED
    else:
        match.status = MatchStatus.NOT_STARTED

    # Validate inputs and constraints (after start time is computed)
    ok, err = validate_match_input(match, tournament_url)
    if not ok:
        db.session.rollback()
        return jsonify({"success": False, "error": err}), 400

    db.session.commit()

    try:
        recompute_all_match_times(tournament_url)
    except Exception:
        pass

    return jsonify({"success": True, "message": "Match added successfully!"}), 200


@bp.route("/<tournament_url>/update-match", methods=["POST"])
@require_tournament_organizer("Only tournament organizers can access this page")
def update_match(tournament_url):
    """Update match."""
    match_id = request.form.get("match_id")
    if not match_id:
        return jsonify({"success": False, "error": "Match ID is required"}), 400

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

    # Allowed schedule type transitions (only these target types allowed from each source)
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
    current_schedule_type = match.schedule_type
    allowed = _ALLOWED_SCHEDULE_TYPE_TRANSITIONS.get(current_schedule_type, (current_schedule_type,))
    if schedule_type not in allowed:
        return (
            jsonify(
                {
                    "success": False,
                    "error": f"Match type cannot be changed from {current_schedule_type.value} to {schedule_type.value}. "
                    "Allowed changes: Static→Safe/Fast, Safe→Fast only.",
                }
            ),
            400,
        )

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

    new_match_name = request.form.get("match_name", match.name)
    mn_err = match_name_char_error(new_match_name)
    if mn_err:
        return jsonify({"success": False, "error": mn_err}), 400

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
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": f'A {schedule_type} match with the name "{new_match_name}" already exists on field "{new_match_field}" in this tournament',
                        }
                    ),
                    400,
                )
        else:
            # For other matches: check uniqueness by (name, event)
            existing_match = Match.query.filter_by(event=tournament_url, name=new_match_name).first()
            if existing_match and existing_match.uuid != match.uuid:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": f'A match with the name "{new_match_name}" already exists in this tournament',
                        }
                    ),
                    400,
                )

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

    if set_type == SetType.STONES:
        stones_per_set_str = request.form.get("stones_per_set")
        if stones_per_set_str:
            try:
                match.stones_per_set = int(stones_per_set_str)
            except (ValueError, TypeError):
                pass  # Keep existing value if invalid
    else:
        # Clear stones_per_set for non-STONES matches
        match.stones_per_set = None

    # JOIN has zero length, BREAK can have length
    if schedule_type == ScheduleType.JOIN:
        match.nominal_length = 0
    elif schedule_type == ScheduleType.BREAK:
        match.nominal_length = int(request.form.get("length", match.nominal_length or 60))
    else:
        match.nominal_length = int(request.form.get("length", match.nominal_length or 60))

    # Update skip_condition (only for SAFE, FAST; clear for STATIC, BREAK, and JOIN)
    skip_condition_raw = request.form.get("skip_condition", "").strip() or None
    match.skip_condition = skip_condition_raw if schedule_type in (ScheduleType.SAFE, ScheduleType.FAST) else None

    # If refs_initial changed, repopulate referee slots with explicit team IDs and resolved tag references
    from app.services.dual_write import (
        clear_match_referees,
        get_match_refs_initial_csv,
        set_match_referees_from_csv,
    )

    old_refs_initial = get_match_refs_initial_csv(match)
    if old_refs_initial != (refs_initial or ""):
        if refs_initial:
            refs_initial_list = [r.strip() for r in refs_initial.split(",")]
            refs_list = [""] * len(refs_initial_list)
            for i, initial_ref in enumerate(refs_initial_list):
                if not initial_ref:
                    continue
                if is_explicit_team_id(initial_ref):
                    refs_list[i] = initial_ref
                else:
                    resolved_team = resolve_tag_to_team(initial_ref, tournament_url)
                    if resolved_team:
                        refs_list[i] = resolved_team
            set_match_referees_from_csv(match, ",".join(refs_list), refs_initial)
        else:
            clear_match_referees(match)

    # For dynamic matches, set previous_match from form and compute start time from it
    # For static matches, ensure previous_match is cleared and use provided start_time
    if schedule_type != ScheduleType.STATIC:
        # Get previous_match from form
        prev_match_id = request.form.get("previous_match", "")
        if prev_match_id:
            # Update doubly linked list: insert this match after prev_match
            update_match_previous_link(match, prev_match_id, tournament_url, is_new=False)
        else:
            # Clear previous_match and update old previous's next_match if needed
            old_prev = match.previous_match
            match.previous_match = None
            if old_prev:
                old_prev_m = Match.query.filter_by(uuid=old_prev, event=tournament_url).first()
                if old_prev_m and old_prev_m.next_match == match.uuid:
                    old_prev_m.next_match = None
        match.nominal_start_time = compute_dynamic_match_nominal_start_time(match, tournament_url)
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

                    match.nominal_start_time = parse_datetime_local_to_utc(request.form["start_time"])
                else:
                    match.nominal_start_time = None
        elif request.form.get("start_time"):
            # Old format: datetime-local (assumed server-local), convert to UTC
            from app.utils.datetime_helpers import parse_datetime_local_to_utc

            match.nominal_start_time = parse_datetime_local_to_utc(request.form["start_time"])
        else:
            match.nominal_start_time = None

    # Validate inputs and constraints
    ok, err = validate_match_input(match, tournament_url)
    if not ok:
        db.session.rollback()
        return jsonify({"success": False, "error": err}), 400

    db.session.flush()  # Flush before updating sequence

    # Recompute all match times (for all dynamic matches that depend on this one)
    recompute_all_match_times(tournament_url)

    db.session.commit()
    return jsonify({"success": True, "message": "Match updated successfully!"}), 200


@bp.route("/<tournament_url>/update-all-references", methods=["POST"])
@require_tournament_organizer("Only tournament organizers can access this page")
def update_all_references(tournament_url):
    """Update all match references (winner/loser) for troubleshooting."""
    from app.utils.dependencies import apply_match_dependencies

    # Get all completed matches (have a winner; skipped matches are excluded)
    completed_matches = Match.query.filter_by(event=tournament_url, status=MatchStatus.COMPLETED).all()

    updated_count = 0
    for match in completed_matches:
        if match.match_winner in ("TEAM1", "TEAM2"):
            try:
                apply_match_dependencies(tournament_url, match)
                updated_count += 1
            except Exception as e:
                print(f"Error updating references for match {match.name}: {e}")

    if updated_count > 0:
        msg = f"Updated references for {updated_count} completed matches"
    else:
        msg = "No references were updated"
    return jsonify({"success": True, "message": msg}), 200


@bp.route("/<tournament_url>/push-back-matches", methods=["POST"])
@require_tournament_organizer("Only tournament organizers can access this page")
def push_back_matches(tournament_url):
    """Push all non-started matches backwards by a specified amount of time (in minutes)."""
    try:
        minutes = int(request.form.get("minutes", 0))
    except (ValueError, TypeError):
        return jsonify({"success": False, "error": "Invalid number of minutes"}), 400

    non_started_matches = (
        Match.query.filter_by(event=tournament_url)
        .filter(~Match.status.in_([MatchStatus.IN_PROGRESS, MatchStatus.COMPLETED, MatchStatus.SKIPPED]))
        .all()
    )

    updated_count = 0
    for match in non_started_matches:
        # Push back nominal_start_time if it exists
        if match.nominal_start_time:
            match.nominal_start_time = match.nominal_start_time + timedelta(minutes=minutes)
            updated_count += 1

        # Also push back confirmed_start_time if it exists (even when start time is already finalized)
        if match.confirmed_start_time:
            match.confirmed_start_time = match.confirmed_start_time + timedelta(minutes=minutes)

    db.session.commit()

    if updated_count > 0:
        msg = f"Pushed back {updated_count} non-started match(es) by {minutes} minute(s)"
    else:
        msg = "No matches were updated. All matches have already started or been completed."
    return jsonify({"success": True, "message": msg}), 200


@bp.route("/<tournament_url>/autocomplete")
def tournament_autocomplete(tournament_url):
    """Autocomplete endpoint for tournament setup.
    Returns a list of suggestions with fields: type, value, label, id
    Supports both standalone events (event=url) and league events (league registrants).
    """
    q_raw = request.args.get("q", "")
    query = (q_raw or "").strip().lower()

    suggestions = []

    tournament = Tournament.query.filter_by(url=tournament_url).first()
    from app.services.registration_resolver import team_registrations_for_tournament

    # Teams registered for this tournament (event or league)
    team_regs = team_registrations_for_tournament(tournament) if tournament else []
    for reg in team_regs:
        pseudonym = (reg.pseudonym or "").strip()
        if not query or query in pseudonym.lower():
            suggestions.append(
                {
                    "type": "team",
                    "value": reg.team,  # Use team ID instead of pseudonym
                    "label": pseudonym,  # Display pseudonym in label
                    "shortname": reg.shortname,
                    "id": reg.team,
                }
            )

    # Tags for this tournament (by name, surfaced as tag::TAG_NAME values)
    tags = Tag.query.filter_by(event=tournament_url).all() if "Tag" in globals() or True else []
    try:
        tags = Tag.query.filter_by(event=tournament_url).all()
    except Exception:
        tags = []
    for t in tags:
        name = (t.name or "").strip()
        if not query or query in name.lower():
            tag_ref = f"tag::{name}"
            suggestions.append({"type": "tag", "value": tag_ref, "label": tag_ref, "id": t.id})

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


@bp.route("/<tournament_url>/validate-dsl", methods=["POST"])
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
        return jsonify({"valid": True, "value": None, "simplified": None, "error": None})

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
        return jsonify({"valid": False, "value": None, "simplified": None, "error": str(e)})
    except Exception as e:
        return jsonify(
            {
                "valid": False,
                "value": None,
                "simplified": None,
                "error": f"Parse error: {str(e)}",
            }
        )


