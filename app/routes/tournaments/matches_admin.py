"""Tournament match / field / tag administrative CRUD endpoints.

Part of the ``tournaments`` blueprint. Uses the same Blueprint object
defined in :mod:`app.routes.tournaments.__init__`.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json

from flask import jsonify, request
from flask_login import current_user, login_required
from sqlalchemy.orm.attributes import flag_modified

from app.domain.enums import ScheduleType, SetType
from app.services.dual_write import (
    clear_match_referees,
    get_match_ref_initials,
    set_match_referees_from_csv,
)
from app.services.permission_service import PermissionService
from app.utils.match_ref_resolution import (
    refs_string_to_tokens,
    resolve_refs_slots,
)
from app.utils.helpers import (
    resolve_team_name_to_id,
    resolve_tag_to_team,
)
from app.utils.name_validation import match_name_char_error
from app.utils.scheduling import (
    compute_dynamic_match_nominal_start_time,
    recompute_all_match_times,
    validate_match_input,
)
from models import (
    Field,
    Match,
    MatchNote,
    Point,
    Tag,
    db,
)

from . import bp, update_match_previous_link


def _check_to(tournament_url):
    if not current_user.is_authenticated:
        return False
    return PermissionService.is_tournament_organizer(tournament_url, current_user)


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
