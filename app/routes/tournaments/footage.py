"""Footage API: TO-authenticated video upload (YouTube link or chunked file).

Replaces the old recording/preview/user-upload pipeline. Creates
match-scoped Camera rows with optional camera_timepoints anchors that the
match page's YouTube-iframe display path reads for jump-to-point.
"""

from flask import request, jsonify, current_app
from flask_login import current_user

import json
import os
import re
import uuid
from os import path

from models import Match, Field, Camera, db
from app.services._common import current_user_type
from app.services.dual_write import get_camera_timepoint_arrays, set_camera_timepoints
from app.utils.decorators import require_tournament_organizer
from app.utils.user_uploads import (
    normalize_anchors,
    create_direct_user_upload_camera,
)

from . import bp

UPLOAD_ID_RE = re.compile(r"[A-Za-z0-9_-]{6,80}")


def _incoming_dir(tournament_url: str, field_name: str, upload_id: str) -> str:
    return path.join(
        current_app.root_path,
        "..",
        "static",
        "uploads",
        "videos",
        tournament_url,
        field_name,
        "user_uploads",
        "_incoming",
        upload_id,
    )


def _resolve_match_field(tournament_url: str, match_id: str):
    match_obj = Match.query.filter_by(uuid=match_id, event=tournament_url).first()
    if not match_obj:
        return None, None, (jsonify({"error": "Match not found"}), 404)
    if not match_obj.field:
        return None, None, (jsonify({"error": "Match has no field"}), 400)
    field_obj = Field.query.filter_by(event=tournament_url, name=match_obj.field).first()
    if not field_obj:
        return None, None, (jsonify({"error": "Match field not found"}), 404)
    return match_obj, field_obj, None


@bp.route("/tournaments/<tournament_url>/matches/<match_id>/footage/link", methods=["POST"])
@require_tournament_organizer()
def footage_link(tournament_url: str, match_id: str):
    """Attach a YouTube link as footage for a match."""
    match_obj, field_obj, err = _resolve_match_field(tournament_url, match_id)
    if err:
        return err

    payload = request.get_json(silent=True) or {}
    youtube_link = (payload.get("youtube_link") or "").strip()
    camera_name = (payload.get("camera_name") or "").strip()
    if not youtube_link:
        return jsonify({"error": "youtube_link is required"}), 400
    if not camera_name:
        return jsonify({"error": "camera_name is required"}), 400

    try:
        worlds, videos = normalize_anchors(match_id, tournament_url, payload.get("anchors"))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    camera = Camera(
        match_uuid=match_id,
        event=tournament_url,
        field=field_obj.id,
        name=camera_name[:200],
        source_type="user_upload",
        uploaded_by_user_id=str(current_user.id),
        uploaded_by_user_type=current_user_type(),
        status="SUCCESS",
        link=youtube_link,
    )
    db.session.add(camera)
    db.session.flush()
    if worlds:
        set_camera_timepoints(camera, worlds, videos)
    db.session.commit()
    return jsonify({"success": True, "camera_uuid": camera.uuid})


@bp.route("/tournaments/<tournament_url>/matches/<match_id>/footage/upload/init", methods=["POST"])
@require_tournament_organizer()
def footage_upload_init(tournament_url: str, match_id: str):
    """Begin a chunked file upload; returns an upload_id."""
    match_obj, field_obj, err = _resolve_match_field(tournament_url, match_id)
    if err:
        return err

    payload = request.get_json(silent=True) or {}
    camera_name = (payload.get("camera_name") or "").strip()
    filename = (payload.get("filename") or "source.mp4").strip()
    content_type = (payload.get("content_type") or "").strip()
    try:
        total_chunks = int(payload.get("total_chunks"))
    except (TypeError, ValueError):
        return jsonify({"error": "total_chunks must be an integer"}), 400
    if total_chunks <= 0:
        return jsonify({"error": "total_chunks must be > 0"}), 400
    if not camera_name:
        return jsonify({"error": "camera_name is required"}), 400

    try:
        normalize_anchors(match_id, tournament_url, payload.get("anchors"))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    upload_id = uuid.uuid4().hex
    incoming = _incoming_dir(tournament_url, match_obj.field, upload_id)
    os.makedirs(incoming, exist_ok=True)
    meta = {
        "upload_id": upload_id,
        "match_uuid": match_id,
        "field_name": match_obj.field,
        "camera_name": camera_name,
        "filename": filename,
        "content_type": content_type,
        "total_chunks": total_chunks,
        "anchors": payload.get("anchors"),
        "uploaded_by_user_id": str(current_user.id),
        "uploaded_by_user_type": current_user_type(),
    }
    with open(path.join(incoming, "meta.json"), "w") as handle:
        json.dump(meta, handle)
    return jsonify({"upload_id": upload_id})


@bp.route("/tournaments/<tournament_url>/matches/<match_id>/footage/upload/chunk", methods=["POST"])
@require_tournament_organizer()
def footage_upload_chunk(tournament_url: str, match_id: str):
    """Receive one chunk of a chunked file upload."""
    upload_id = (request.form.get("upload_id") or "").strip()
    chunk_index_raw = (request.form.get("chunk_index") or "").strip()
    chunk_file = request.files.get("chunk")
    if not upload_id or not UPLOAD_ID_RE.fullmatch(upload_id):
        return jsonify({"error": "Invalid upload_id"}), 400
    if chunk_file is None:
        return jsonify({"error": "chunk is required"}), 400

    match_obj = Match.query.filter_by(uuid=match_id, event=tournament_url).first()
    if not match_obj or not match_obj.field:
        return jsonify({"error": "Match not found"}), 404
    incoming = _incoming_dir(tournament_url, match_obj.field, upload_id)
    meta_path = path.join(incoming, "meta.json")
    if not path.exists(meta_path):
        return jsonify({"error": "Upload not found"}), 404
    with open(meta_path) as handle:
        meta = json.load(handle)

    try:
        chunk_index = int(chunk_index_raw)
    except ValueError:
        return jsonify({"error": "chunk_index must be an integer"}), 400
    if chunk_index < 0 or chunk_index >= int(meta["total_chunks"]):
        return jsonify({"error": "chunk_index out of range"}), 400

    chunk_file.save(path.join(incoming, f"chunk_{chunk_index:06d}.part"))
    return jsonify({"success": True})


@bp.route("/tournaments/<tournament_url>/matches/<match_id>/footage/upload/complete", methods=["POST"])
@require_tournament_organizer()
def footage_upload_complete(tournament_url: str, match_id: str):
    """Assemble chunks, create the Camera row, and start the YouTube upload."""
    payload = request.get_json(silent=True) or {}
    upload_id = (payload.get("upload_id") or "").strip()
    if not upload_id or not UPLOAD_ID_RE.fullmatch(upload_id):
        return jsonify({"error": "Invalid upload_id"}), 400

    match_obj = Match.query.filter_by(uuid=match_id, event=tournament_url).first()
    if not match_obj or not match_obj.field:
        return jsonify({"error": "Match not found"}), 404
    incoming = _incoming_dir(tournament_url, match_obj.field, upload_id)
    meta_path = path.join(incoming, "meta.json")
    if not path.exists(meta_path):
        return jsonify({"error": "Upload not found"}), 404
    with open(meta_path) as handle:
        meta = json.load(handle)

    if str(meta.get("uploaded_by_user_id")) != str(current_user.id):
        return jsonify({"error": "You cannot complete another user's upload"}), 403

    total_chunks = int(meta["total_chunks"])
    ext = path.splitext(path.basename(meta.get("filename") or "source.mp4"))[1].lower() or ".mp4"
    source_path = path.join(incoming, f"source{ext}")
    with open(source_path, "wb") as out:
        for i in range(total_chunks):
            part = path.join(incoming, f"chunk_{i:06d}.part")
            if not path.exists(part):
                return jsonify({"error": f"Missing chunk {i}"}), 400
            with open(part, "rb") as inp:
                while True:
                    buf = inp.read(1024 * 1024)
                    if not buf:
                        break
                    out.write(buf)

    app_obj = current_app._get_current_object()  # type: ignore[attr-defined]
    try:
        camera_uuid = create_direct_user_upload_camera(
            current_app.logger,
            app_obj,
            tournament_url=tournament_url,
            match_uuid=match_id,
            camera_name=meta.get("camera_name") or "",
            upload_key=upload_id,
            saved_abs_path=source_path,
            uploader_user_id=str(current_user.id),
            uploader_user_type=current_user_type(),
            anchors=meta.get("anchors"),
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    for i in range(total_chunks):
        part = path.join(incoming, f"chunk_{i:06d}.part")
        if path.exists(part):
            os.remove(part)

    return jsonify({"success": True, "camera_uuid": camera_uuid})


@bp.route("/tournaments/<tournament_url>/matches/<match_id>/footage", methods=["GET"])
@require_tournament_organizer()
def list_match_footage(tournament_url: str, match_id: str):
    """List cameras attached to a match."""
    cams = Camera.query.filter_by(match_uuid=match_id, event=tournament_url).order_by(Camera.name.asc()).all()
    return jsonify(
        {
            "cameras": [
                {
                    "uuid": c.uuid,
                    "name": c.name,
                    "status": c.status,
                    "link": c.link,
                    "source_type": c.source_type,
                }
                for c in cams
            ]
        }
    )


@bp.route("/tournaments/<tournament_url>/matches/<match_id>/footage/<camera_uuid>", methods=["DELETE"])
@require_tournament_organizer()
def delete_match_footage(tournament_url: str, match_id: str, camera_uuid: str):
    """Delete a camera (and its timepoints + local file)."""
    cam = Camera.query.filter_by(uuid=camera_uuid, event=tournament_url, match_uuid=match_id).first()
    if not cam:
        return jsonify({"error": "Camera not found"}), 404
    if cam.file:
        try:
            abs_fp = path.join(current_app.root_path, "..", cam.file)
            if os.path.exists(abs_fp):
                os.remove(abs_fp)
        except OSError:
            pass
    set_camera_timepoints(cam, [], [])
    db.session.delete(cam)
    db.session.commit()
    return jsonify({"success": True})


@bp.route("/tournaments/<tournament_url>/footage", methods=["GET"])
@require_tournament_organizer()
def list_event_footage(tournament_url: str):
    """List all cameras for an event (backs the Manage Footage page)."""
    cams = Camera.query.filter_by(event=tournament_url).order_by(Camera.match_uuid.asc(), Camera.name.asc()).all()
    rows = []
    for cam in cams:
        match_obj = Match.query.filter_by(uuid=cam.match_uuid).first()
        field_obj = Field.query.filter_by(id=cam.field).first()
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
                "match_name": match_obj.name if match_obj else cam.match_uuid,
                "field_name": field_obj.name if field_obj else str(cam.field),
                "camera_name": cam.name,
                "status": cam.status,
                "user": uploader,
                "world_start_timestamp": world_start,
                "link": cam.link,
            }
        )
    return jsonify({"cameras": rows})
