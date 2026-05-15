"""Camera/recording and user-upload routes.

Camera endpoints, the record/* preview/upload pipeline, ffmpeg
finalisation, the retry endpoint, and the user-upload pipeline
(including its private helpers). Part of the ``tournaments`` blueprint.
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


@bp.route("/camera-url")
@login_required
def camera_url_api():
    """Generate camera recording URL with access key. Requires TO access."""
    try:
        tournament_url = request.args.get("tournament")
        field_name = request.args.get("field")

        if not tournament_url or not field_name:
            return jsonify({"error": "Tournament and field parameters required"}), 400

        # Check if user is a TO for this tournament
        if not PermissionService.is_tournament_organizer(tournament_url, current_user):
            return (
                jsonify({"error": "Unauthorized: You must be a TO for this tournament"}),
                403,
            )

        # Verify field exists
        field = Field.query.filter_by(event=tournament_url, name=field_name).first()
        if not field:
            return jsonify({"error": f'Field "{field_name}" not found'}), 404

        # Generate the camera URL with key (frontend route, not a Flask endpoint)
        access_key = generate_camera_key(tournament_url, field_name)
        from urllib.parse import quote

        base = request.url_root.rstrip("/")
        camera_url = (
            f"{base}/{tournament_url}/record?field={quote(field_name)}&camera_key={quote(access_key)}&camera_name="
        )

        return jsonify({"url": camera_url})
    except Exception as e:
        import traceback

        print(f"Error in camera_url_api: {e}")
        print(traceback.format_exc())
        return jsonify({"error": f"Server error: {str(e)}"}), 500


@bp.route("/record/match-status")
def record_match_status():
    """Check if a field has an active match for point recording. No access key required."""
    from models import Point

    tournament_url = request.args.get("tournament")
    field_name = request.args.get("field")
    current_match_id = request.args.get("current_match_id")  # Optional: track specific match

    if not tournament_url or not field_name:
        return jsonify({"error": "Tournament and field parameters required"}), 400

    # Verify field exists
    field = Field.query.filter_by(event=tournament_url, name=field_name).first()
    if not field:
        return jsonify({"error": "Field not found"}), 404

    preview_requested = preview_store.is_preview_requested(tournament_url, field_name)

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
                    end_stamp_str = end_stamp_str.replace("+00:00", "Z").replace("-00:00", "Z")
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
        match = Match.query.filter_by(uuid=current_match_id, event=tournament_url).first()
        if match:
            # Continue recording if match is still IN_PROGRESS (not yet finalized)
            if match.status == MatchStatus.IN_PROGRESS:
                return jsonify(
                    {
                        "hasActiveMatch": True,
                        "match_id": match.uuid,
                        "match_name": match.name,
                        "start_time": (match.confirmed_start_time.isoformat() if match.confirmed_start_time else None),
                        "status": match.status,
                        "points": get_points_data(match),
                        "preview_requested": preview_requested,
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
                        "preview_requested": preview_requested,
                    }
                )
        else:
            # Match not found - might have been deleted, stop recording
            return jsonify(
                {
                    "hasActiveMatch": False,
                    "reason": "match_not_found",
                    "preview_requested": preview_requested,
                }
            )

    # No specific match tracked - find any active match on this field
    match = Match.query.filter_by(event=tournament_url, field=field_name, status=MatchStatus.IN_PROGRESS).first()

    if match:
        return jsonify(
            {
                "hasActiveMatch": True,
                "match_id": match.uuid,
                "match_name": match.name,
                "start_time": (match.confirmed_start_time.isoformat() if match.confirmed_start_time else None),
                "status": match.status,
                "points": get_points_data(match),
                "preview_requested": preview_requested,
            }
        )
    else:
        return jsonify(
            {
                "hasActiveMatch": False,
                "preview_requested": preview_requested,
            }
        )


@bp.route("/record/request-preview", methods=["POST"])
@login_required
def record_request_preview():
    """TO requests preview for a field; creates sentinel so record pages send frames."""
    data = request.get_json(silent=True) or {}
    tournament_url = (data.get("tournament") or request.args.get("tournament") or "").strip()
    field_name = (data.get("field") or request.args.get("field") or "").strip()
    if not tournament_url or not field_name:
        return jsonify({"error": "tournament and field required"}), 400
    if not PermissionService.is_tournament_organizer(tournament_url, current_user):
        return jsonify({"error": "Only tournament organizers can request preview"}), 403
    field = Field.query.filter_by(event=tournament_url, name=field_name).first()
    if not field:
        return jsonify({"error": "Field not found"}), 404
    preview_store.set_preview_requested(tournament_url, field_name)
    return jsonify({"success": True})


@bp.route("/record/release-preview", methods=["POST", "DELETE"])
@login_required
def record_release_preview():
    """TO releases preview for a field; deletes sentinel and optionally cleans pending/serving."""
    data = request.get_json(silent=True) or {}
    tournament_url = (data.get("tournament") or request.args.get("tournament") or "").strip()
    field_name = (data.get("field") or request.args.get("field") or "").strip()
    if not tournament_url or not field_name:
        return jsonify({"error": "tournament and field required"}), 400
    if not PermissionService.is_tournament_organizer(tournament_url, current_user):
        return jsonify({"error": "Only tournament organizers can release preview"}), 403
    preview_store.clear_preview_requested(tournament_url, field_name)
    return jsonify({"success": True})


@bp.route("/record/preview-frame", methods=["POST"])
def record_preview_frame_post():
    """Record page uploads a preview frame (JPEG). Writes to path A (pending). Requires camera_key."""
    tournament_url = (request.args.get("tournament") or request.form.get("tournament") or "").strip()
    field_name = (request.args.get("field") or request.form.get("field") or "").strip()
    camera_name = (request.args.get("camera_name") or request.form.get("camera_name") or "camera").strip() or "camera"
    if not tournament_url or not field_name:
        return jsonify({"error": "tournament and field required"}), 400
    is_valid, error_response = require_camera_key(tournament_url, field_name)
    if not is_valid:
        return error_response[0], error_response[1]
    field = Field.query.filter_by(event=tournament_url, name=field_name).first()
    if not field:
        return jsonify({"error": "Field not found"}), 404
    data = request.get_data()
    if not data:
        return jsonify({"error": "No image data"}), 400
    preview_store.write_pending(tournament_url, field_name, camera_name, data)
    return jsonify({"success": True})


@bp.route("/record/preview-frame-consumed", methods=["GET"])
def record_preview_frame_consumed():
    """Record page polls: true if no file at A (frame was consumed by TO). Requires camera_key."""
    tournament_url = request.args.get("tournament", "").strip()
    field_name = request.args.get("field", "").strip()
    camera_name = (request.args.get("camera_name") or "camera").strip() or "camera"
    if not tournament_url or not field_name:
        return jsonify({"error": "tournament and field required"}), 400
    is_valid, error_response = require_camera_key(tournament_url, field_name)
    if not is_valid:
        return error_response[0], error_response[1]
    consumed = not preview_store.has_pending(tournament_url, field_name, camera_name)
    return jsonify({"consumed": consumed})


@bp.route("/record/preview-metadata", methods=["POST"])
def record_preview_metadata_post():
    """Record page sends device metadata (storage, battery) with camera_key. Optional fields."""
    tournament_url = (request.args.get("tournament") or (request.json or {}).get("tournament") or "").strip()
    field_name = (request.args.get("field") or (request.json or {}).get("field") or "").strip()
    camera_name = (
        request.args.get("camera_name") or (request.json or {}).get("camera_name") or "camera"
    ).strip() or "camera"
    if not tournament_url or not field_name:
        return jsonify({"error": "tournament and field required"}), 400
    is_valid, error_response = require_camera_key(tournament_url, field_name)
    if not is_valid:
        return error_response[0], error_response[1]
    data = request.get_json(silent=True) or {}
    storage_usage = data.get("storage_usage")
    storage_quota = data.get("storage_quota")
    battery_level = data.get("battery_level")
    if storage_usage is not None:
        storage_usage = float(storage_usage)
    if storage_quota is not None:
        storage_quota = float(storage_quota)
    if battery_level is not None:
        battery_level = float(battery_level)
    preview_store.write_metadata(
        tournament_url,
        field_name,
        camera_name,
        storage_usage,
        storage_quota,
        battery_level,
    )
    return jsonify({"success": True})


@bp.route("/record/preview-metadata", methods=["GET"])
@login_required
def record_preview_metadata_get():
    """TO: get device metadata for a camera (storage, battery). Returns JSON or 204."""
    tournament_url = request.args.get("tournament", "").strip()
    field_name = request.args.get("field", "").strip()
    camera_name = (request.args.get("camera_name") or "camera").strip() or "camera"
    if not tournament_url or not field_name:
        return jsonify({"error": "tournament and field required"}), 400
    if not PermissionService.is_tournament_organizer(tournament_url, current_user):
        return (
            jsonify({"error": "Only tournament organizers can get preview metadata"}),
            403,
        )
    meta = preview_store.read_metadata(tournament_url, field_name, camera_name)
    if not meta:
        return "", 204
    return jsonify(meta)


@bp.route("/record/preview-cameras", methods=["GET"])
@login_required
def record_preview_cameras():
    """TO: list camera_name s that have a recent frame for this field (for dropdown)."""
    tournament_url = request.args.get("tournament", "").strip()
    field_name = request.args.get("field", "").strip()
    if not tournament_url or not field_name:
        return jsonify({"error": "tournament and field required"}), 400
    if not PermissionService.is_tournament_organizer(tournament_url, current_user):
        return (
            jsonify({"error": "Only tournament organizers can list preview cameras"}),
            403,
        )
    field = Field.query.filter_by(event=tournament_url, name=field_name).first()
    if not field:
        return jsonify({"error": "Field not found"}), 404
    cameras = preview_store.list_cameras_with_recent_frame(tournament_url, field_name)
    return jsonify({"cameras": cameras})


@bp.route("/record/preview-frame", methods=["GET"])
@login_required
def record_preview_frame_get():
    """TO: get latest preview frame for a camera. Moves A→B then serves B, or serves stale B or 204."""
    from flask import send_file, make_response
    import io

    tournament_url = request.args.get("tournament", "").strip()
    field_name = request.args.get("field", "").strip()
    camera_name = (request.args.get("camera_name") or "camera").strip() or "camera"
    if not tournament_url or not field_name:
        return jsonify({"error": "tournament and field required"}), 400
    if not PermissionService.is_tournament_organizer(tournament_url, current_user):
        return (
            jsonify({"error": "Only tournament organizers can get preview frame"}),
            403,
        )
    # Prevent Safari (and others) from caching; Safari may not send cookies with img requests.
    no_cache_headers = {
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
    }
    # Move pending to serving if we have a new frame
    preview_store.move_pending_to_serving(tournament_url, field_name, camera_name)
    data, mtime = preview_store.read_serving(tournament_url, field_name, camera_name)
    if not data:
        resp = make_response("", 204)
        resp.headers.update(no_cache_headers)
        return resp
    # Optional: treat stale B as "camera offline" after RECENT_MTIME_SEC
    if mtime and (time.time() - mtime) > preview_store.RECENT_MTIME_SEC:
        resp = make_response("", 204)
        resp.headers.update(no_cache_headers)
        return resp
    resp = send_file(
        io.BytesIO(data),
        mimetype="image/jpeg",
        as_attachment=False,
    )
    resp.headers.update(no_cache_headers)
    return resp


@bp.route("/record/upload-chunk", methods=["POST"])
def record_upload_chunk():
    """Receive one fMP4 fragment for point recording (container=mp4). Camera key required."""
    import os
    from flask import current_app
    import fcntl

    tournament_url = request.form.get("tournament")
    field_name = request.form.get("field")
    match_id = request.form.get("match_id")
    session_id = request.form.get("session_id")
    chunk_start_timestamp = request.form.get("chunk_start_timestamp")  # Absolute world time when chunk started
    recording_session_start_time = request.form.get("recording_session_start_time")
    chunk_duration = request.form.get("chunk_duration")  # Duration in milliseconds
    camera_name = request.form.get("camera_name")
    blob_event_timestamp_ms_raw = request.form.get("blob_event_timestamp_ms")
    is_init_segment_raw = request.form.get("is_init_segment")
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
    db.session.remove()

    if "chunk" not in request.files:
        return jsonify({"error": "No chunk file provided"}), 400

    chunk_file = request.files["chunk"]
    if chunk_file.filename == "":
        return jsonify({"error": "Empty chunk file"}), 400

    # New record page: fragmented MP4 only (fMP4 from MediaRecorder).
    container = (request.form.get("container") or "mp4").strip().lower()
    if container != "mp4":
        return jsonify({"error": "Only container=mp4 is supported"}), 400
    chunk_ext = "mp4"

    upload_dir = os.path.join(
        current_app.root_path,
        "../static/uploads/videos",
        tournament_url,
        field_name,
        match_id,
        camera_name,
    )
    os.makedirs(upload_dir, exist_ok=True)

    chunks_meta_path = os.path.join(upload_dir, "chunks_meta.json")

    def parse_timestamp(val):
        if val is None or val == "":
            return None
        s = str(val).strip()
        if not s:
            return None
        try:
            return float(val)
        except (TypeError, ValueError):
            pass
        if "T" in s and ("Z" in s or "+" in s or "-" in s[-6:]):
            return s  # Store ISO string as-is; footage.py accepts both
        try:
            return float(s)
        except ValueError:
            return s

    def parse_float_opt(val):
        if val is None or val == "":
            return None
        try:
            return float(val)
        except (TypeError, ValueError):
            return None

    def parse_bool(val):
        if val is None:
            return False
        return str(val).strip().lower() in {"1", "true", "yes", "on"}

    chunk_index = None
    try:
        file_mode = "r+" if os.path.exists(chunks_meta_path) else "w+"
        with open(chunks_meta_path, file_mode) as lock_file:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except IOError:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)

            lock_file.seek(0)
            content = lock_file.read()
            if content.strip():
                try:
                    chunks_meta = json.loads(content)
                except (json.JSONDecodeError, ValueError):
                    chunks_meta = {}
            else:
                chunks_meta = {}

            # Assign index under lock so concurrent uploads never get same index or overwrite
            chunk_index = len(chunks_meta)
            chunk_filename = f"chunk_{chunk_index}.{chunk_ext}"
            chunk_path = os.path.join(upload_dir, chunk_filename)
            chunk_file.save(chunk_path)

            chunk_meta = {
                "filename": chunk_filename,
                "session_id": session_id,
                "chunk_start_timestamp": parse_timestamp(chunk_start_timestamp),
                "chunk_duration": float(chunk_duration),
                "camera_name": camera_name,
                "recording_session_start_time": parse_timestamp(recording_session_start_time),
                "blob_event_timestamp_ms": parse_float_opt(blob_event_timestamp_ms_raw),
                "is_init_segment": parse_bool(is_init_segment_raw),
            }
            chunks_meta[str(chunk_index)] = chunk_meta

            lock_file.seek(0)
            lock_file.truncate(0)
            json.dump(chunks_meta, lock_file, indent=2)
            lock_file.flush()
    except (IOError, OSError):
        print("error writing :sob:")
        return jsonify({"error": "Failed to save chunk"}), 500

    try:
        with open(chunk_path, "rb") as f:
            head = f.read(4)
        file_size = os.path.getsize(chunk_path)
        current_app.logger.info(
            "record chunk %s: size=%s bytes, ext=%s, first4=%s",
            chunk_index,
            file_size,
            chunk_ext,
            head.hex() if len(head) == 4 else "short",
        )
    except Exception as e:
        current_app.logger.warning("record chunk debug read failed: %s", e)

    return jsonify({"success": True, "chunk_index": chunk_index, "session_id": session_id})


@bp.route("/record/finalize", methods=["POST"])
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

    # Worker runs in a background thread; it must run inside an app context for db.session to persist.
    app = current_app._get_current_object()
    logger = current_app.logger
    current_app.logger.info(
        "record_finalize: submitting worker for match_id=%s camera_name=%s chunk_dir=%s",
        match_id,
        camera_name,
        chunk_dir,
    )

    def run_finalize_with_app_context():
        with app.app_context():
            finalize_recording_worker(
                logger,
                tournament_url,
                field_name,
                match_id,
                camera_name,
                chunk_dir,
            )

    _ = executor.submit(run_finalize_with_app_context)

    # For now, just return success
    return jsonify(
        {
            "success": True,
            "message": "all recordings uploaded; processing has begun",
            "match_id": match_id,
        }
    )


@bp.route(
    "/tournaments/<tournament_url>/matches/<match_id>/retry-finalization",
    methods=["POST"],
)
@login_required
def retry_match_finalization(tournament_url: str, match_id: str):
    import os

    if not current_user_can_retry_finalization(current_user):
        return (
            jsonify(
                {
                    "success": False,
                    "error": (
                        f"Forbidden. Add your user id to {RETRY_FINALIZATION_USER_IDS_ENV} "
                        "to enable retry finalization."
                    ),
                }
            ),
            403,
        )

    match = Match.query.filter_by(uuid=match_id, event=tournament_url).first()
    if not match:
        return jsonify({"success": False, "error": "Match not found"}), 404
    if not match.field:
        return jsonify({"success": False, "error": "Match has no field"}), 400
    field_name = match.field

    root_dir = os.path.join(
        current_app.root_path,
        "../static/uploads/videos",
        tournament_url,
        field_name,
        match_id,
    )
    if not os.path.isdir(root_dir):
        return (
            jsonify(
                {
                    "success": False,
                    "error": "No recording artifacts found for this match",
                }
            ),
            404,
        )

    chunk_dirs: list[tuple[str, str]] = []
    for camera_name in sorted(os.listdir(root_dir)):
        chunk_dir = os.path.join(root_dir, camera_name)
        if not os.path.isdir(chunk_dir):
            continue
        if not os.path.exists(os.path.join(chunk_dir, "chunks_meta.json")):
            continue
        chunk_dirs.append((camera_name, chunk_dir))

    if not chunk_dirs:
        return (
            jsonify({"success": False, "error": "No chunk metadata found for this match"}),
            404,
        )

    app = current_app._get_current_object()
    logger = current_app.logger
    for camera_name, chunk_dir in chunk_dirs:
        logger.info(
            "retry_match_finalization: submitting worker for match_id=%s camera_name=%s chunk_dir=%s requested_by=%s",
            match_id,
            camera_name,
            chunk_dir,
            getattr(current_user, "id", None),
        )

        def run_finalize_with_app_context(chunk_dir: str = chunk_dir, camera_name: str = camera_name):
            with app.app_context():
                finalize_recording_worker(
                    logger,
                    tournament_url,
                    field_name,
                    match_id,
                    camera_name,
                    chunk_dir,
                )

        _ = executor.submit(run_finalize_with_app_context)

    return jsonify(
        {
            "success": True,
            "message": f"Requeued finalization for {len(chunk_dirs)} recording(s).",
        }
    )


@bp.route("/tournaments/<tournament_url>/user-upload", methods=["POST"])
@login_required
def user_upload_video_footage(tournament_url: str):
    """Authenticated endpoint for raw clip generation or direct edited uploads."""
    import os

    _tournament, err = _require_registered_player_for_upload(tournament_url)
    if err:
        return err

    try:
        upload_mode = _normalize_user_upload_mode(request.form.get("upload_mode"))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    field_id_raw = request.form.get("field_id") or request.form.get("field")
    match_uuid = (request.form.get("match_uuid") or "").strip() or None

    video_file = request.files.get("video") or request.files.get("file")
    if not video_file or video_file.filename == "":
        return jsonify({"error": "video file is required"}), 400

    start_world_override = request.form.get("start_world") or request.form.get("start_timestamp")
    try:
        start_world_override = _normalize_user_upload_start_world(start_world_override)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    camera_name_override = (request.form.get("camera_name") or "").strip()
    field_obj = None
    field_name_resolved = None
    if upload_mode == "raw_clips":
        if not field_id_raw:
            return jsonify({"error": "field_id is required for raw clip uploads"}), 400
        try:
            field_id = int(field_id_raw)
        except ValueError:
            return jsonify({"error": "field_id must be an integer"}), 400
        field_obj = Field.query.filter_by(event=tournament_url, id=field_id).first()
        if not field_obj:
            return jsonify({"error": "Field not found"}), 404
        field_name_resolved = field_obj.name
    else:
        if not match_uuid:
            return jsonify({"error": "match_uuid is required for edited uploads"}), 400
        match_obj = Match.query.filter_by(uuid=match_uuid, event=tournament_url).first()
        if not match_obj:
            return jsonify({"error": "Match not found"}), 404
        if not match_obj.field:
            return jsonify({"error": "Selected match has no field"}), 400
        field_name_resolved = match_obj.field

    db.session.remove()

    upload_group_name = uuid.uuid4().hex[:12]
    original_filename = video_file.filename
    orig_stem = path.splitext(path.basename(original_filename))[0] or "upload"
    if camera_name_override:
        orig_stem = camera_name_override
    ext = path.splitext(original_filename)[1].lower()
    if not ext:
        ext = ".webm"

    upload_dir = path.join(
        current_app.root_path,
        "../static/uploads/videos",
        tournament_url,
        field_name_resolved,
        "user_uploads",
        upload_group_name,
    )
    os.makedirs(upload_dir, exist_ok=True)

    saved_name = f"source{ext}"
    saved_abs_path = path.join(upload_dir, saved_name)
    video_file.save(saved_abs_path)

    uploader_user_id = str(current_user.id)
    uploader_user_type = current_user_type()

    app_obj = current_app._get_current_object()  # type: ignore[attr-defined]
    logger = current_app.logger

    batch_camera_name = camera_name_override or orig_stem
    try:
        if upload_mode == "edited_match":
            create_direct_user_upload_camera(
                logger,
                app_obj,
                tournament_url=tournament_url,
                match_uuid=match_uuid or "",
                camera_name=batch_camera_name,
                upload_key=upload_group_name,
                saved_abs_path=saved_abs_path,
                uploader_user_id=uploader_user_id,
                uploader_user_type=uploader_user_type,
            )
        else:
            register_batch_upload_completion(
                logger,
                app_obj,
                tournament_url=tournament_url,
                field_name=field_name_resolved,
                batch_id=upload_group_name,
                batch_index=0,
                batch_total=1,
                camera_name=batch_camera_name,
                upload_id=upload_group_name,
                saved_abs_path=saved_abs_path,
                start_world_override=start_world_override,
                incoming_dir_name=None,
                uploader_user_id=uploader_user_id,
                uploader_user_type=uploader_user_type,
            )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    return jsonify(
        {
            "success": True,
            "message": (
                "Upload received; YouTube upload has begun."
                if upload_mode == "edited_match"
                else "Upload received; processing has begun."
            ),
            "upload_group_name": upload_group_name,
        }
    )


def _user_upload_incoming_dir_name(upload_id: str, batch_index: int) -> str:
    """Return the expected directory name for an upload batch.

    Args:
        upload_id: The unique upload session identifier.
        batch_index: Zero-based index of this batch within the session.

    Returns:
        A string of the form ``"<upload_id>__<batch_index:06d>"``.
    """
    return f"{upload_id}__{batch_index:06d}"


def _locate_user_upload_incoming_dir(tournament_url: str, upload_id: str, batch_index: int | None = None):
    """Search all fields for an in-progress user-upload directory.

    Looks in ``static/uploads/videos/<tournament>/<field>/user_uploads/_incoming/``
    for a directory whose name or whose ``meta.json`` content matches
    *upload_id* and optionally *batch_index*.

    Args:
        tournament_url: Tournament URL slug used to scope the search.
        upload_id: The unique upload session identifier to look for.
        batch_index: Optional batch index; when provided, only directories
            with a matching ``batch_index`` in ``meta.json`` are returned.

    Returns:
        A ``(abs_path, field_name)`` tuple when found, or ``(None, None)``
        when no matching directory exists.
    """
    incoming_root = path.join(
        current_app.root_path,
        "../static/uploads/videos",
        tournament_url,
    )

    for field_obj in Field.query.filter_by(event=tournament_url).all():
        incoming_base = path.join(
            incoming_root,
            field_obj.name,
            "user_uploads",
            "_incoming",
        )
        if not path.isdir(incoming_base):
            continue

        candidate_names = []
        if batch_index is not None:
            candidate_names.append(_user_upload_incoming_dir_name(upload_id, batch_index))
        candidate_names.append(upload_id)

        for dir_name in candidate_names:
            candidate = path.join(incoming_base, dir_name)
            if path.exists(candidate):
                return candidate, field_obj.name

        for dir_name in listdir(incoming_base):
            candidate = path.join(incoming_base, dir_name)
            meta_path = path.join(candidate, "meta.json")
            if not path.exists(meta_path):
                continue
            try:
                with open(meta_path, "r") as f:
                    meta = json.load(f)
            except (OSError, json.JSONDecodeError):
                continue
            if str(meta.get("upload_id") or "").strip() != upload_id:
                continue
            if batch_index is not None:
                try:
                    existing_batch_index = int(meta.get("batch_index") if meta.get("batch_index") is not None else 0)
                except (TypeError, ValueError):
                    existing_batch_index = 0
                if existing_batch_index != batch_index:
                    continue
            return candidate, field_obj.name

    return None, None


def _normalize_user_upload_start_world(raw_value: str | None) -> str | None:
    """Parse and normalise a ``start_world`` upload timestamp to UTC ISO format.

    Accepts any ISO-8601 string with a timezone designator (including ``Z``).

    Args:
        raw_value: Raw timestamp string from the request, or ``None``.

    Returns:
        UTC ISO-8601 string ending with ``"Z"``, or ``None`` when *raw_value*
        is empty or ``None``.

    Raises:
        ValueError: If the value is not a valid timezone-aware ISO timestamp.
    """
    if raw_value is None:
        return None
    s = raw_value.strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError as exc:
        raise ValueError("start_world must be an ISO timestamp with timezone, e.g. 2026-03-18T01:23:45Z") from exc
    if dt.tzinfo is None:
        raise ValueError("start_world must include timezone, e.g. 2026-03-18T01:23:45Z or 2026-03-17T18:23:45-07:00")
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalize_user_upload_mode(raw_value: str | None) -> str:
    """Normalise the user-upload mode string to a canonical value.

    Accepts several alias strings and maps them to ``"raw_clips"`` or
    ``"edited_match"``.

    Args:
        raw_value: Raw mode string from the request, or ``None``.

    Returns:
        ``"raw_clips"`` or ``"edited_match"``.

    Raises:
        ValueError: If *raw_value* is not a recognised mode alias.
    """
    mode = (raw_value or "raw_clips").strip().lower()
    if mode in ("raw_clips", "raw", "clips"):
        return "raw_clips"
    if mode in ("edited_match", "edited", "direct"):
        return "edited_match"
    raise ValueError("upload_mode must be raw_clips or edited_match")


def _require_registered_player_for_upload(tournament_url: str):
    tournament = Tournament.query.filter_by(url=tournament_url).first()
    if not tournament:
        return None, (jsonify({"error": "Tournament not found"}), 404)
    if current_user_type() != "player":
        return None, (
            jsonify({"error": "Only registered players can upload footage"}),
            403,
        )
    if not is_player_registered(tournament, str(current_user.id)):
        return None, (
            jsonify({"error": "You must be registered for this tournament to upload footage"}),
            403,
        )
    return tournament, None


@bp.route("/tournaments/<tournament_url>/user-upload/planning", methods=["GET"])
@login_required
def user_upload_planning(tournament_url: str):
    _, err = _require_registered_player_for_upload(tournament_url)
    if err:
        return err

    field_id_raw = (request.args.get("field_id") or request.args.get("field") or "").strip()
    if not field_id_raw:
        return jsonify({"error": "field_id is required"}), 400
    try:
        field_id = int(field_id_raw)
    except ValueError:
        return jsonify({"error": "field_id must be an integer"}), 400

    field_obj = Field.query.filter_by(event=tournament_url, id=field_id).first()
    if not field_obj:
        return jsonify({"error": "Field not found"}), 404

    matches = (
        Match.query.filter_by(event=tournament_url, field=field_obj.name)
        .order_by(
            Match.confirmed_start_time.asc(),
            Match.nominal_start_time.asc(),
            Match.name.asc(),
        )
        .all()
    )
    match_ids = [m.uuid for m in matches]
    points_by_match: dict[str, list[Point]] = {m.uuid: [] for m in matches}
    if match_ids:
        points = Point.query.filter(Point.match.in_(match_ids)).order_by(Point.stamp.asc(), Point.uuid.asc()).all()
        for pt in points:
            if pt.match:
                points_by_match.setdefault(pt.match, []).append(pt)

    rows = []
    for match_obj in matches:
        match_points = []
        for idx, pt in enumerate(points_by_match.get(match_obj.uuid, []), start=1):
            match_points.append(
                {
                    "uuid": str(pt.uuid),
                    "index": idx,
                    "stamp": (
                        pt.stamp.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z") if pt.stamp else None
                    ),
                    "end_stamp": (
                        pt.end_stamp.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
                        if pt.end_stamp
                        else None
                    ),
                }
            )
        rows.append(
            {
                "uuid": str(match_obj.uuid),
                "name": match_obj.name,
                "field_name": field_obj.name,
                "points": match_points,
            }
        )

    return jsonify(
        {
            "field": {"id": field_obj.id, "name": field_obj.name},
            "matches": rows,
        }
    )


@bp.route("/tournaments/<tournament_url>/user-upload/chunk", methods=["POST"])
@login_required
def user_upload_video_footage_chunk(tournament_url: str):
    """
    Chunked upload endpoint for large user footage files.
    Each request contains one chunk (<100MB from frontend).
    """
    import os
    import re

    _tournament, err = _require_registered_player_for_upload(tournament_url)
    if err:
        return err

    field_id_raw = request.form.get("field_id") or request.form.get("field")
    match_uuid = (request.form.get("match_uuid") or "").strip() or None
    try:
        upload_mode = _normalize_user_upload_mode(request.form.get("upload_mode"))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    upload_id = (request.form.get("upload_id") or "").strip()
    chunk_index_raw = (request.form.get("chunk_index") or "").strip()
    total_chunks_raw = (request.form.get("total_chunks") or "").strip()
    filename = (request.form.get("filename") or "source.webm").strip()
    content_type = (request.form.get("content_type") or "").strip()
    start_world_override = (request.form.get("start_world") or "").strip() or None
    camera_name_override = (request.form.get("camera_name") or "").strip() or None
    chunk_file = request.files.get("chunk")

    batch_id_raw = (request.form.get("batch_id") or "").strip()
    batch_index_raw = (request.form.get("batch_index") or "").strip()
    batch_total_raw = (request.form.get("batch_total") or "").strip()

    if not upload_id or chunk_file is None:
        return jsonify({"error": "upload_id and chunk are required"}), 400
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,80}", upload_id):
        return jsonify({"error": "Invalid upload_id"}), 400

    try:
        chunk_index = int(chunk_index_raw)
        total_chunks = int(total_chunks_raw)
    except ValueError:
        return jsonify({"error": "chunk_index and total_chunks must be integers"}), 400
    if chunk_index < 0 or total_chunks <= 0 or chunk_index >= total_chunks:
        return jsonify({"error": "Invalid chunk_index/total_chunks"}), 400

    try:
        batch_total = int(batch_total_raw) if batch_total_raw != "" else 1
    except ValueError:
        return jsonify({"error": "batch_total must be an integer"}), 400
    try:
        batch_index = int(batch_index_raw) if batch_index_raw != "" else 0
    except ValueError:
        return jsonify({"error": "batch_index must be an integer"}), 400
    if batch_total < 1 or batch_index < 0 or batch_index >= batch_total:
        return jsonify({"error": "Invalid batch_index/batch_total"}), 400

    if batch_total > 1:
        if not batch_id_raw or not re.fullmatch(r"[A-Za-z0-9_-]{6,80}", batch_id_raw):
            return jsonify({"error": "batch_id is required when batch_total > 1"}), 400
        batch_id = batch_id_raw
    else:
        batch_id = batch_id_raw or upload_id
    try:
        start_world_override = _normalize_user_upload_start_world(start_world_override)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    filename_stem = path.splitext(path.basename(filename))[0] or "upload"
    batch_camera_name = (camera_name_override or "").strip() or filename_stem

    field_obj = None
    field_name_resolved = None
    if upload_mode == "raw_clips":
        if not field_id_raw:
            return jsonify({"error": "field_id is required for raw clip uploads"}), 400
        try:
            field_id = int(field_id_raw)
        except ValueError:
            return jsonify({"error": "field_id must be an integer"}), 400
        field_obj = Field.query.filter_by(event=tournament_url, id=field_id).first()
        if not field_obj:
            return jsonify({"error": "Field not found"}), 404
        field_name_resolved = field_obj.name
    else:
        if not match_uuid:
            return jsonify({"error": "match_uuid is required for edited uploads"}), 400
        match_obj = Match.query.filter_by(uuid=match_uuid, event=tournament_url).first()
        if not match_obj:
            return jsonify({"error": "Match not found"}), 404
        if not match_obj.field:
            return jsonify({"error": "Selected match has no field"}), 400
        field_name_resolved = match_obj.field
        field_obj = Field.query.filter_by(event=tournament_url, name=field_name_resolved).first()
        if not field_obj:
            return jsonify({"error": "Match field not found"}), 404
        field_id = field_obj.id

    db.session.remove()
    incoming_dir_name = _user_upload_incoming_dir_name(upload_id, batch_index)

    incoming_dir = path.join(
        current_app.root_path,
        "../static/uploads/videos",
        tournament_url,
        field_name_resolved,
        "user_uploads",
        "_incoming",
        incoming_dir_name,
    )
    os.makedirs(incoming_dir, exist_ok=True)

    meta_path = path.join(incoming_dir, "meta.json")
    if path.exists(meta_path):
        with open(meta_path, "r") as f:
            existing = json.load(f)
        if existing.get("upload_id") != upload_id:
            return jsonify({"error": "upload_id mismatch"}), 400
        if int(existing.get("total_chunks") or 0) != total_chunks:
            return jsonify({"error": "total_chunks mismatch"}), 400
        if existing.get("batch_id") != batch_id:
            return jsonify({"error": "batch_id mismatch"}), 400
        if int(existing.get("batch_total") or 0) != batch_total:
            return jsonify({"error": "batch_total mismatch"}), 400
        existing_batch_index = existing.get("batch_index")
        try:
            existing_batch_index = int(existing_batch_index) if existing_batch_index is not None else -1
        except (TypeError, ValueError):
            existing_batch_index = -1
        if existing_batch_index != batch_index:
            current_app.logger.warning(
                "user_upload chunk batch_index mismatch: upload_id=%s incoming_dir=%s existing_batch_index=%s request_batch_index=%s batch_id=%s existing_meta=%s",
                upload_id,
                incoming_dir,
                existing_batch_index,
                batch_index,
                batch_id,
                meta_path,
            )
            return jsonify({"error": "batch_index mismatch"}), 400
        if existing.get("batch_camera_name") != batch_camera_name:
            return jsonify({"error": "camera_name mismatch"}), 400
        if int(existing.get("field_id") or 0) != field_id:
            return jsonify({"error": "field_id mismatch"}), 400
        if str(existing.get("upload_mode") or "raw_clips") != upload_mode:
            return jsonify({"error": "upload_mode mismatch"}), 400
        if (str(existing.get("match_uuid") or "").strip() or None) != match_uuid:
            return jsonify({"error": "match_uuid mismatch"}), 400

    chunk_filename = f"chunk_{chunk_index:06d}.part"
    chunk_abs_path = path.join(incoming_dir, chunk_filename)
    chunk_file.save(chunk_abs_path)

    meta = {
        "upload_id": upload_id,
        "tournament_url": tournament_url,
        "field_id": field_id,
        "field_name": field_name_resolved,
        "filename": filename,
        "content_type": content_type,
        "upload_mode": upload_mode,
        "match_uuid": match_uuid,
        "total_chunks": total_chunks,
        "start_world_override": start_world_override,
        "camera_name_override": camera_name_override,
        "batch_id": batch_id,
        "batch_index": batch_index,
        "batch_total": batch_total,
        "batch_camera_name": batch_camera_name,
        "incoming_dir_name": incoming_dir_name,
        "uploaded_by_user_id": str(current_user.id),
        "uploaded_by_user_type": current_user_type(),
    }
    with open(meta_path, "w") as f:
        json.dump(meta, f)

    return jsonify(
        {
            "success": True,
            "upload_id": upload_id,
            "chunk_index": chunk_index,
            "total_chunks": total_chunks,
        }
    )


@bp.route("/tournaments/<tournament_url>/user-upload/complete", methods=["POST"])
@login_required
def user_upload_video_footage_complete(tournament_url: str):
    """Finalize a chunked upload, assemble source file on disk, then start processing worker."""
    import os

    _tournament, err = _require_registered_player_for_upload(tournament_url)
    if err:
        return err

    payload = request.get_json(silent=True) or {}
    upload_id = (payload.get("upload_id") or request.form.get("upload_id") or "").strip()
    if not upload_id:
        return jsonify({"error": "upload_id is required"}), 400

    batch_index_raw = payload.get("batch_index")
    if batch_index_raw is None:
        batch_index_raw = request.form.get("batch_index")
    if batch_index_raw in (None, ""):
        batch_index = None
    else:
        try:
            batch_index = int(batch_index_raw)
        except (TypeError, ValueError):
            return jsonify({"error": "batch_index must be an integer"}), 400

    incoming_dir, field_name = _locate_user_upload_incoming_dir(tournament_url, upload_id, batch_index)
    if not incoming_dir or not field_name:
        return jsonify({"error": "Upload not found"}), 404
    db.session.remove()

    meta_path = path.join(incoming_dir, "meta.json")
    if not path.exists(meta_path):
        return jsonify({"error": "Upload metadata missing"}), 400

    with open(meta_path, "r") as f:
        meta = json.load(f)

    if str(meta.get("uploaded_by_user_id")) != str(current_user.id):
        return jsonify({"error": "You cannot complete another user's upload"}), 403

    total_chunks = int(meta.get("total_chunks") or 0)
    if total_chunks <= 0:
        return jsonify({"error": "Invalid total_chunks metadata"}), 400

    filename = meta.get("filename") or "source.webm"
    ext = path.splitext(path.basename(filename))[1].lower() or ".webm"
    incoming_dir_name = (meta.get("incoming_dir_name") or "").strip() or path.basename(incoming_dir)
    final_dir = path.join(
        current_app.root_path,
        "../static/uploads/videos",
        tournament_url,
        field_name,
        "user_uploads",
        incoming_dir_name,
    )
    os.makedirs(final_dir, exist_ok=True)
    saved_abs_path = path.join(final_dir, f"source{ext}")

    # Assemble chunk files in order without loading entire upload into RAM.
    with open(saved_abs_path, "wb") as out:
        for i in range(total_chunks):
            part_path = path.join(incoming_dir, f"chunk_{i:06d}.part")
            if not path.exists(part_path):
                return jsonify({"error": f"Missing chunk {i}"}), 400
            with open(part_path, "rb") as inp:
                while True:
                    buf = inp.read(1024 * 1024)
                    if not buf:
                        break
                    out.write(buf)

    start_world_override = meta.get("start_world_override")
    try:
        start_world_override = _normalize_user_upload_start_world(start_world_override)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    try:
        upload_mode = _normalize_user_upload_mode(meta.get("upload_mode"))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    match_uuid = (meta.get("match_uuid") or "").strip() or None

    batch_id = (meta.get("batch_id") or "").strip() or upload_id
    try:
        batch_index = int(meta.get("batch_index") if meta.get("batch_index") is not None else 0)
    except (TypeError, ValueError):
        batch_index = 0
    try:
        batch_total = int(meta.get("batch_total") if meta.get("batch_total") is not None else 1)
    except (TypeError, ValueError):
        batch_total = 1
    batch_camera_name = (meta.get("batch_camera_name") or "").strip()
    if not batch_camera_name:
        co = (meta.get("camera_name_override") or "").strip()
        batch_camera_name = co or path.splitext(path.basename(filename))[0] or "upload"

    uploader_user_id = str(current_user.id)
    uploader_user_type = current_user_type()

    app_obj = current_app._get_current_object()  # type: ignore[attr-defined]
    logger = current_app.logger

    try:
        if upload_mode == "edited_match":
            if not match_uuid:
                return (
                    jsonify({"error": "match_uuid is required for edited uploads"}),
                    400,
                )
            create_direct_user_upload_camera(
                logger,
                app_obj,
                tournament_url=tournament_url,
                match_uuid=match_uuid,
                camera_name=batch_camera_name,
                upload_key=upload_id,
                saved_abs_path=saved_abs_path,
                uploader_user_id=uploader_user_id,
                uploader_user_type=uploader_user_type,
            )
        else:
            register_batch_upload_completion(
                logger,
                app_obj,
                tournament_url=tournament_url,
                field_name=field_name,
                batch_id=batch_id,
                batch_index=batch_index,
                batch_total=batch_total,
                camera_name=batch_camera_name,
                upload_id=upload_id,
                saved_abs_path=saved_abs_path,
                start_world_override=start_world_override,
                incoming_dir_name=incoming_dir_name,
                uploader_user_id=uploader_user_id,
                uploader_user_type=uploader_user_type,
            )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    # Best-effort cleanup of chunk parts after assembly.
    try:
        for i in range(total_chunks):
            part_path = path.join(incoming_dir, f"chunk_{i:06d}.part")
            if path.exists(part_path):
                os.remove(part_path)
    except Exception:
        pass

    return jsonify(
        {
            "success": True,
            "message": (
                "Upload received; YouTube upload has begun."
                if upload_mode == "edited_match"
                else "Upload received; processing has begun."
            ),
            "upload_group_name": upload_id,
        }
    )


@bp.route(
    "/tournaments/<tournament_url>/user-upload/delete-camera/<camera_uuid>",
    methods=["DELETE"],
)
@require_tournament_organizer()
def user_upload_delete_camera(tournament_url: str, camera_uuid: str):
    """TO-only: delete a user-uploaded camera highlight."""
    import os

    cam = Camera.query.filter_by(uuid=camera_uuid, event=tournament_url).filter_by(source_type="user_upload").first()
    if not cam:
        return jsonify({"error": "Camera not found"}), 404

    # Best-effort local file cleanup.
    if cam.file:
        try:
            abs_fp = path.join(current_app.root_path, "..", cam.file)
            if os.path.exists(abs_fp):
                os.remove(abs_fp)
        except Exception:
            pass

    db.session.delete(cam)
    db.session.commit()
    return jsonify({"success": True})


@bp.route("/tournaments/<tournament_url>/user-uploaded-cameras", methods=["GET"])
@require_tournament_organizer()
def user_upload_list_cameras(tournament_url: str):
    """TO-only: list user-uploaded cameras so TOs can moderate/delete them."""
    cams = (
        Camera.query.filter_by(event=tournament_url, source_type="user_upload")
        .order_by(Camera.match_uuid.asc(), Camera.name.asc())
        .all()
    )

    from app.services.dual_write import get_camera_timepoint_arrays

    rows = []
    for cam in cams:
        m = Match.query.filter_by(uuid=cam.match_uuid).first()
        f = Field.query.filter_by(id=cam.field).first()
        worlds, _ = get_camera_timepoint_arrays(cam)
        world_start = str(worlds[0]) if worlds and worlds[0] is not None else None
        uploader = None
        if cam.uploaded_by_user_type and cam.uploaded_by_user_id:
            uploader = f"{cam.uploaded_by_user_type}:{cam.uploaded_by_user_id}"
        elif cam.uploaded_by_user_id:
            uploader = str(cam.uploaded_by_user_id)
        rows.append(
            {
                "uuid": cam.uuid,
                "match_uuid": cam.match_uuid,
                "match_name": m.name if m else cam.match_uuid,
                "field_name": f.name if f else str(cam.field),
                "camera_name": cam.name,
                "status": cam.status,
                "user": uploader,
                "world_start_timestamp": world_start,
                "link": cam.link,
                "file": cam.file,
                "uploaded_by_user_id": cam.uploaded_by_user_id,
                "uploaded_by_user_type": cam.uploaded_by_user_type,
                "manifest_only": False,
                "error": None,
            }
        )

    rows.extend(list_batch_manifest_rows(tournament_url))
    return jsonify({"cameras": rows})


