from __future__ import annotations

import fcntl
import json
import os
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from os import path
from typing import Any, Optional

from flask import current_app

from models import Camera, Field, Match, Point, db
from app.utils.youtube_upload import upload_camera_to_youtube


def _run_ffprobe_json(args: list[str]) -> dict:
    result = subprocess.run(
        ["ffprobe", "-v", "error", *args, "-of", "json"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr or result.stdout}")
    return json.loads(result.stdout or "{}")


def _get_media_duration_sec(file_path: str) -> float:
    """
    Return duration in seconds via ffprobe.
    """
    args = [
        "-show_entries",
        "format=duration",
        file_path,
    ]
    data = _run_ffprobe_json(args)
    dur = data.get("format", {}).get("duration")
    if dur is None:
        return 0.0
    try:
        return float(dur)
    except ValueError:
        return 0.0


def _parse_iso_to_datetime_utc(s: str) -> Optional[datetime]:
    if not s:
        return None
    s = s.strip()
    if not s:
        return None
    # Normalize trailing Z.
    if s.endswith("Z"):
        s_norm = s.replace("Z", "+00:00")
    else:
        s_norm = s
    try:
        dt = datetime.fromisoformat(s_norm)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt
    except ValueError:
        return None


def _get_video_start_world_datetime(file_path: str) -> datetime:
    """
    Best-effort: extract start timestamp from common tags.
    Falls back to filesystem mtime (UTC).
    """
    # ffprobe format_tags commonly has creation_time for MP4/MOV and sometimes webm tags.
    # Also check Apple-style tag if present.
    try:
        args = [
            "-show_entries",
            "format_tags=creation_time:format_tags=com.apple.quicktime.creationdate",
            file_path,
        ]
        data = _run_ffprobe_json(args)
        tags = data.get("format", {}).get("tags") or {}
        candidates = [
            tags.get("creation_time"),
            tags.get("com.apple.quicktime.creationdate"),
        ]
        for c in candidates:
            if isinstance(c, str) and c.strip():
                dt = _parse_iso_to_datetime_utc(c)
                if dt:
                    return dt
    except Exception:
        # Fall back below
        pass

    # Fallback: filesystem mtime.
    mtime = os.path.getmtime(file_path)
    return datetime.fromtimestamp(mtime, tz=timezone.utc)


def _dt_to_iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class UserUploadClipPlan:
    point_uuid: str
    point_start_world: datetime
    point_end_world: datetime
    clip_start_file_sec: float
    clip_end_file_sec: float
    point_start_in_clip_sec: float


def build_clip_plans_for_points(
    *,
    video_start_world: datetime,
    video_duration_sec: float,
    points: list[Point],
    padding_sec: float = 3.0,
) -> list[UserUploadClipPlan]:
    plans: list[UserUploadClipPlan] = []
    from datetime import timedelta

    video_end_world = video_start_world + timedelta(seconds=video_duration_sec)

    for pt in points:
        if pt.stamp is None:
            continue
        pt_start = pt.stamp.replace(tzinfo=timezone.utc)
        pt_end = pt.end_stamp.replace(tzinfo=timezone.utc) if pt.end_stamp else pt_start

        # If it doesn't overlap the video time range, skip.
        if pt_start > video_end_world or pt_end < video_start_world:
            continue

        clip_start_world = pt_start - timedelta(seconds=padding_sec)
        clip_end_world = pt_end + timedelta(seconds=padding_sec)

        # Clamp to the source file window.
        clip_start_world = max(clip_start_world, video_start_world)
        clip_end_world = min(clip_end_world, video_end_world)

        clip_start_file_sec = (clip_start_world - video_start_world).total_seconds()
        clip_end_file_sec = (clip_end_world - video_start_world).total_seconds()

        if clip_end_file_sec <= clip_start_file_sec:
            continue

        point_start_in_clip_sec = (pt_start - clip_start_world).total_seconds()
        plans.append(
            UserUploadClipPlan(
                point_uuid=str(pt.uuid),
                point_start_world=pt_start,
                point_end_world=pt_end,
                clip_start_file_sec=clip_start_file_sec,
                clip_end_file_sec=clip_end_file_sec,
                point_start_in_clip_sec=point_start_in_clip_sec,
            )
        )

    plans.sort(key=lambda p: p.point_start_world)
    return plans


def _ffmpeg_trim_to_webm(
    *,
    input_path: str,
    start_sec: float,
    end_sec: float,
    output_path: str,
) -> None:
    duration = max(0.0, end_sec - start_sec)
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        input_path,
        "-ss",
        str(start_sec),
        "-t",
        str(duration),
        "-c:v",
        "libvpx-vp9",
        "-crf",
        "30",
        "-b:v",
        "0",
        "-row-mt",
        "1",
        "-c:a",
        "libopus",
        "-b:a",
        "128k",
        output_path,
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def _ffmpeg_concat_webm(
    *,
    clip_paths: list[str],
    output_path: str,
) -> None:
    if not clip_paths:
        raise RuntimeError("No clip paths to concat")
    if len(clip_paths) == 1:
        # Copy/rename the single clip to output.
        shutil.copy2(clip_paths[0], output_path)
        return

    concat_list = path.join(path.dirname(output_path), "concat_points.txt")
    with open(concat_list, "w") as f:
        for cp in clip_paths:
            f.write(f"file {repr(path.abspath(cp))}\n")
    concat_list_abs = path.abspath(concat_list)

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        concat_list_abs,
        "-c:v",
        "libvpx-vp9",
        "-crf",
        "30",
        "-b:v",
        "0",
        "-row-mt",
        "1",
        "-c:a",
        "libopus",
        "-b:a",
        "128k",
        "-y",
        output_path,
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def _static_root() -> str:
    return path.normpath(path.join(current_app.root_path, "..", "static"))


def batch_manifest_path(tournament_url: str, field_name: str, batch_id: str) -> str:
    return path.join(
        _static_root(),
        "uploads",
        "videos",
        tournament_url,
        field_name,
        "user_uploads",
        "_batches",
        batch_id,
        "manifest.json",
    )


def _slug_camera_dir(s: str, max_len: int = 48) -> str:
    t = re.sub(r"[^a-zA-Z0-9._-]+", "_", s.strip())[:max_len]
    return t or "cam"


def _camera_fs_dir_name(batch_id: str, camera_display_name: str) -> str:
    slug = _slug_camera_dir(camera_display_name)
    name = f"{batch_id}_{slug}"
    return name[:120]


def _manifest_read_write_locked(manifest_path: str, mutator: Any) -> Any:
    """mutator receives dict or None (missing), returns new dict to write."""
    os.makedirs(path.dirname(manifest_path), exist_ok=True)
    with open(manifest_path, "a+", encoding="utf-8") as fp:
        fcntl.flock(fp.fileno(), fcntl.LOCK_EX)
        try:
            fp.seek(0)
            raw = fp.read()
            data: Optional[dict[str, Any]] = None
            if raw.strip():
                data = json.loads(raw)
            new_data = mutator(data)
            fp.seek(0)
            fp.truncate()
            fp.write(json.dumps(new_data, indent=2))
            fp.flush()
            return new_data
        finally:
            fcntl.flock(fp.fileno(), fcntl.LOCK_UN)


def _manifest_set_status(manifest_path: str, status: str, error: Optional[str] = None) -> None:
    def _m(data: Optional[dict[str, Any]]) -> dict[str, Any]:
        if not data:
            return {"status": status, "error": error}
        data = dict(data)
        data["status"] = status
        if error is not None:
            data["error"] = error
        return data

    _manifest_read_write_locked(manifest_path, _m)


def _cleanup_batch_processing_artifacts(
    manifest_path: str,
    *,
    logger=None,
    remove_manifest_dir: bool = False,
) -> None:
    """
    Remove temporary per-upload source files after batch processing is finished.
    Keeps failed manifests by default so the management UI can still show them.
    """
    _log = logger or current_app.logger
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    except (OSError, json.JSONDecodeError):
        if remove_manifest_dir and path.isdir(path.dirname(manifest_path)):
            try:
                shutil.rmtree(path.dirname(manifest_path))
            except OSError:
                _log.warning(
                    "user_autoclips batch: could not remove manifest dir %s",
                    path.dirname(manifest_path),
                )
        return

    static_root = _static_root()
    tournament_url = str(manifest.get("tournament_url") or "").strip()
    field_name = str(manifest.get("field_name") or "").strip()
    files_map: dict[str, Any] = manifest.get("files") or {}

    dirs_to_remove: set[str] = set()
    for entry in files_map.values():
        if not isinstance(entry, dict):
            continue
        source_relpath = str(entry.get("source_relpath") or "").strip()
        if source_relpath:
            source_abs_path = path.normpath(path.join(static_root, source_relpath))
            dirs_to_remove.add(path.dirname(source_abs_path))

        incoming_dir_name = str(entry.get("incoming_dir_name") or "").strip()
        upload_id = str(entry.get("upload_id") or "").strip()
        if tournament_url and field_name and (incoming_dir_name or upload_id):
            dirs_to_remove.add(
                path.join(
                    static_root,
                    "uploads",
                    "videos",
                    tournament_url,
                    field_name,
                    "user_uploads",
                    "_incoming",
                    incoming_dir_name or upload_id,
                )
            )

    for dir_path in sorted(dirs_to_remove, key=len, reverse=True):
        if not path.isdir(dir_path):
            continue
        try:
            shutil.rmtree(dir_path)
        except OSError:
            _log.warning(
                "user_autoclips batch: could not remove temp dir %s",
                dir_path,
            )

    if remove_manifest_dir:
        manifest_dir = path.dirname(manifest_path)
        if path.isdir(manifest_dir):
            try:
                shutil.rmtree(manifest_dir)
            except OSError:
                _log.warning(
                    "user_autoclips batch: could not remove manifest dir %s",
                    manifest_dir,
                )


def _finalize_batch_status(
    manifest_path: str,
    *,
    status: str,
    error: Optional[str] = None,
    logger=None,
    remove_manifest_dir: bool = False,
) -> None:
    _manifest_set_status(manifest_path, status, error)
    _cleanup_batch_processing_artifacts(
        manifest_path,
        logger=logger,
        remove_manifest_dir=remove_manifest_dir,
    )


def register_batch_upload_completion(
    logger,
    app_obj,
    *,
    tournament_url: str,
    field_name: str,
    batch_id: str,
    batch_index: int,
    batch_total: int,
    camera_name: str,
    upload_id: str,
    saved_abs_path: str,
    start_world_override: Optional[str],
    incoming_dir_name: Optional[str],
    uploader_user_id: str,
    uploader_user_type: str,
) -> None:
    """
    Record one assembled source file in the batch manifest. When all slots are
    filled, spawn user_autoclips_from_uploaded_batch_worker in a daemon thread.
    Raises ValueError if manifest metadata conflicts with this upload.
    """
    _log = logger or current_app.logger
    saved_abs_path = path.abspath(path.normpath(saved_abs_path))
    static_root = _static_root()
    try:
        source_relpath = path.relpath(saved_abs_path, static_root).replace("\\", "/")
    except ValueError as e:
        raise ValueError("assembled file is not under the static root") from e

    manifest_path = batch_manifest_path(tournament_url, field_name, batch_id)
    display_name = (camera_name or "").strip() or "upload"
    if len(display_name) > 200:
        display_name = display_name[:200]

    spawned = False

    def _append(data: Optional[dict[str, Any]]) -> dict[str, Any]:
        nonlocal spawned
        if data is None:
            data = {
                "batch_id": batch_id,
                "batch_total": batch_total,
                "camera_name": display_name,
                "field_name": field_name,
                "tournament_url": tournament_url,
                "uploader_user_id": uploader_user_id,
                "uploader_user_type": uploader_user_type,
                "status": "pending",
                "files": {},
            }
        else:
            if data.get("batch_id") != batch_id:
                raise ValueError("batch_id mismatch")
            if int(data.get("batch_total") or 0) != batch_total:
                raise ValueError("batch_total mismatch")
            if data.get("camera_name") != display_name:
                raise ValueError("camera_name mismatch")
            if data.get("field_name") != field_name:
                raise ValueError("field_name mismatch")
            if data.get("tournament_url") != tournament_url:
                raise ValueError("tournament_url mismatch")
            if str(data.get("uploader_user_id")) != str(uploader_user_id):
                raise ValueError("uploader mismatch")

        files: dict[str, Any] = dict(data.get("files") or {})
        files[str(batch_index)] = {
            "upload_id": upload_id,
            "source_relpath": source_relpath,
            "start_world_override": start_world_override,
            "incoming_dir_name": incoming_dir_name,
        }
        data = dict(data)
        data["files"] = files

        ready = len(files) >= batch_total and all(
            str(i) in files for i in range(batch_total)
        )
        if ready and data.get("status") == "pending":
            data["status"] = "processing"
            spawned = True
        return data

    try:
        _manifest_read_write_locked(manifest_path, _append)
    except ValueError:
        raise

    if spawned:

        def _run() -> None:
            with app_obj.app_context():
                try:
                    user_autoclips_from_uploaded_batch_worker(
                        _log,
                        manifest_path=manifest_path,
                        tournament_url=tournament_url,
                        field_name=field_name,
                    )
                except Exception:
                    _log.exception("user_autoclips batch worker failed")
                    try:
                        _finalize_batch_status(
                            manifest_path,
                            status="failed",
                            error="worker exception",
                            logger=_log,
                        )
                    except Exception:
                        pass

        threading.Thread(target=_run, daemon=True).start()


def list_batch_manifest_rows(tournament_url: str) -> list[dict[str, Any]]:
    """
    Return manifest-backed rows for uploads that have not yet produced visible
    camera rows, so the management page can show pending/failed batches.
    """
    tournament_root = path.join(_static_root(), "uploads", "videos", tournament_url)
    if not path.isdir(tournament_root):
        return []

    rows: list[dict[str, Any]] = []
    for field_name in os.listdir(tournament_root):
        batches_root = path.join(
            tournament_root, field_name, "user_uploads", "_batches"
        )
        if not path.isdir(batches_root):
            continue
        for batch_id in os.listdir(batches_root):
            manifest_path = path.join(batches_root, batch_id, "manifest.json")
            if not path.exists(manifest_path):
                continue
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
            except (OSError, json.JSONDecodeError):
                continue

            status = str(manifest.get("status") or "pending").strip().lower() or "pending"
            if status == "done":
                continue

            files_map = manifest.get("files") or {}
            world_start = None
            for idx in sorted(files_map.keys(), key=lambda raw: int(raw) if str(raw).isdigit() else raw):
                entry = files_map.get(idx) or {}
                sw = (entry.get("start_world_override") or "").strip()
                if sw:
                    world_start = sw
                    break

            uploader = None
            uploader_user_type = str(manifest.get("uploader_user_type") or "").strip() or None
            uploader_user_id = str(manifest.get("uploader_user_id") or "").strip() or None
            if uploader_user_type and uploader_user_id:
                uploader = f"{uploader_user_type}:{uploader_user_id}"
            elif uploader_user_id:
                uploader = uploader_user_id

            error = str(manifest.get("error") or "").strip() or None
            rows.append(
                {
                    "uuid": f"batch:{field_name}:{batch_id}",
                    "match_uuid": "",
                    "match_name": "Pending batch",
                    "field_name": str(manifest.get("field_name") or field_name),
                    "camera_name": str(manifest.get("camera_name") or "upload"),
                    "status": status.upper(),
                    "user": uploader,
                    "world_start_timestamp": world_start,
                    "link": None,
                    "file": None,
                    "uploaded_by_user_id": uploader_user_id,
                    "uploaded_by_user_type": uploader_user_type,
                    "manifest_only": True,
                    "error": error,
                }
            )

    return rows


def user_autoclips_from_uploaded_batch_worker(
    logger,
    *,
    manifest_path: str,
    tournament_url: str,
    field_name: str,
    match_points_padding_sec: float = 3.0,
):
    """
    Merge clip plans across all sources in the batch manifest (per match), then
    create one Camera per match with the shared display name.
    """
    _log = logger or current_app.logger
    static_root = _static_root()

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    batch_total = int(manifest.get("batch_total") or 0)
    batch_id_key = (manifest.get("batch_id") or "").strip() or "batch"
    camera_display_name = (manifest.get("camera_name") or "").strip() or "upload"
    if len(camera_display_name) > 200:
        camera_display_name = camera_display_name[:200]

    uploader_user_id = str(manifest.get("uploader_user_id") or "")
    uploader_user_type = str(manifest.get("uploader_user_type") or "")
    files_map: dict[str, Any] = manifest.get("files") or {}

    sources: list[tuple[str, Optional[str]]] = []
    for i in range(batch_total):
        entry = files_map.get(str(i))
        if not entry:
            _log.error("user_autoclips batch: missing file index %s", i)
            _finalize_batch_status(
                manifest_path,
                status="failed",
                error="missing file slot",
                logger=_log,
            )
            return
        rel = entry.get("source_relpath") or ""
        abs_path = path.normpath(path.join(static_root, rel))
        if not path.exists(abs_path):
            _log.error("user_autoclips batch: missing source %s", abs_path)
            _finalize_batch_status(
                manifest_path,
                status="failed",
                error="source missing",
                logger=_log,
            )
            return
        sw = entry.get("start_world_override")
        if isinstance(sw, str) and sw.strip():
            sources.append((abs_path, sw.strip()))
        else:
            sources.append((abs_path, None))

    field_obj = Field.query.filter_by(event=tournament_url, name=field_name).first()
    if not field_obj:
        _log.error("user_autoclips batch: field not found event=%s field=%s", tournament_url, field_name)
        _finalize_batch_status(
            manifest_path,
            status="failed",
            error="field not found",
            logger=_log,
        )
        return

    matches = Match.query.filter_by(event=tournament_url, field=field_name).all()
    if not matches:
        _log.warning("user_autoclips batch: no matches field=%s event=%s", field_name, tournament_url)
        _finalize_batch_status(
            manifest_path,
            status="failed",
            error="no matches found on selected field",
            logger=_log,
        )
        return

    uuid_to_match = {m.uuid: m for m in matches}
    match_ids = [m.uuid for m in matches]
    points = Point.query.filter(Point.match.in_(match_ids)).order_by(Point.stamp.asc()).all()

    points_by_match: dict[str, list[Point]] = {}
    for pt in points:
        if not pt.match:
            continue
        points_by_match.setdefault(pt.match, []).append(pt)
    if not points_by_match:
        _log.warning(
            "user_autoclips batch: no recorded points field=%s event=%s",
            field_name,
            tournament_url,
        )
        _finalize_batch_status(
            manifest_path,
            status="failed",
            error="no recorded points found on selected field",
            logger=_log,
        )
        db.session.remove()
        return
    # Release DB connection before per-match ffmpeg (same rationale as finalize_recording_worker).
    db.session.remove()

    camera_fs_name = _camera_fs_dir_name(batch_id_key, camera_display_name)
    created_cameras = 0

    for match_uuid, pts in points_by_match.items():
        combined: list[tuple[UserUploadClipPlan, str]] = []
        for user_video_abs_path, video_start_world_override_iso in sources:
            user_video_abs_path = path.abspath(path.normpath(user_video_abs_path))
            video_duration_sec = _get_media_duration_sec(user_video_abs_path)
            if video_duration_sec <= 0:
                _log.error(
                    "user_autoclips batch: bad duration for %s", user_video_abs_path
                )
                continue

            if video_start_world_override_iso:
                override_dt = _parse_iso_to_datetime_utc(video_start_world_override_iso)
                video_start_world = override_dt or _get_video_start_world_datetime(
                    user_video_abs_path
                )
            else:
                video_start_world = _get_video_start_world_datetime(user_video_abs_path)

            plans = build_clip_plans_for_points(
                video_start_world=video_start_world,
                video_duration_sec=video_duration_sec,
                points=pts,
                padding_sec=match_points_padding_sec,
            )
            for p in plans:
                combined.append((p, user_video_abs_path))

        combined.sort(key=lambda x: x[0].point_start_world)
        deduped: list[tuple[UserUploadClipPlan, str]] = []
        seen_uuids: set[str] = set()
        for plan, src in combined:
            if plan.point_uuid in seen_uuids:
                continue
            seen_uuids.add(plan.point_uuid)
            deduped.append((plan, src))

        if not deduped:
            continue

        if match_uuid not in uuid_to_match:
            continue

        match_out_dir = path.join(
            current_app.root_path,
            "..",
            "static",
            "uploads",
            "videos",
            tournament_url,
            field_name,
            match_uuid,
            camera_fs_name,
        )
        os.makedirs(match_out_dir, exist_ok=True)

        src_clips_dir = path.join(match_out_dir, "clips")
        os.makedirs(src_clips_dir, exist_ok=True)

        clip_paths: list[str] = []
        time_world: list[str] = []
        time_video: list[float] = []

        concat_offset = 0.0
        for i, (plan, user_video_abs_path) in enumerate(deduped):
            clip_name = f"point_clip_{i}.webm"
            clip_abs_path = path.join(src_clips_dir, clip_name)
            _ffmpeg_trim_to_webm(
                input_path=user_video_abs_path,
                start_sec=plan.clip_start_file_sec,
                end_sec=plan.clip_end_file_sec,
                output_path=clip_abs_path,
            )
            clip_paths.append(clip_abs_path)

            point_start_in_highlight = concat_offset + plan.point_start_in_clip_sec
            time_world.append(_dt_to_iso_z(plan.point_start_world))
            time_video.append(round(point_start_in_highlight, 3))

            concat_offset += max(0.0, plan.clip_end_file_sec - plan.clip_start_file_sec)

        final_highlight_abs_path = path.join(match_out_dir, "final_video.webm")
        _ffmpeg_concat_webm(clip_paths=clip_paths, output_path=final_highlight_abs_path)

        final_highlight_rel = path.join(
            "static",
            "uploads",
            "videos",
            tournament_url,
            field_name,
            match_uuid,
            camera_fs_name,
            "final_video.webm",
        ).replace("\\", "/")

        camera_row = Camera(
            match_uuid=match_uuid,
            event=tournament_url,
            field=field_obj.id,
            name=camera_display_name,
            source_type="user_upload",
            uploaded_by_user_id=uploader_user_id,
            uploaded_by_user_type=uploader_user_type,
            status="UPLOADING",
            file=final_highlight_rel,
            time_world=json.dumps(time_world),
            time_video=json.dumps(time_video),
        )
        db.session.add(camera_row)
        db.session.commit()

        app_obj = current_app._get_current_object()

        def _yt_upload():
            with app_obj.app_context():
                upload_camera_to_youtube(str(camera_row.uuid))

        threading.Thread(target=_yt_upload, daemon=True).start()

        _log.info(
            "user_autoclips batch: created camera uuid=%s match=%s clips=%d",
            camera_row.uuid,
            match_uuid,
            len(deduped),
        )
        created_cameras += 1

    if created_cameras == 0:
        _log.warning(
            "user_autoclips batch: no clips matched field=%s event=%s batch=%s",
            field_name,
            tournament_url,
            batch_id_key,
        )
        _finalize_batch_status(
            manifest_path,
            status="failed",
            error="no clips matched uploaded footage; check file start timestamps",
            logger=_log,
        )
        return

    _finalize_batch_status(
        manifest_path,
        status="done",
        logger=_log,
        remove_manifest_dir=True,
    )


def create_direct_user_upload_camera(
    logger,
    app_obj,
    *,
    tournament_url: str,
    match_uuid: str,
    camera_name: str,
    upload_key: str,
    saved_abs_path: str,
    uploader_user_id: str,
    uploader_user_type: str,
) -> str:
    """
    Create a single match-scoped camera from a pre-edited upload and start the
    YouTube upload immediately. No point timing metadata is attached.
    """
    _log = logger or current_app.logger

    match_obj = Match.query.filter_by(uuid=match_uuid, event=tournament_url).first()
    if not match_obj:
        raise ValueError("Match not found")
    if not match_obj.field:
        raise ValueError("Selected match has no field")

    field_obj = Field.query.filter_by(event=tournament_url, name=match_obj.field).first()
    if not field_obj:
        raise ValueError("Match field not found")

    display_name = (camera_name or "").strip() or (
        path.splitext(path.basename(saved_abs_path))[0] or "upload"
    )
    if len(display_name) > 200:
        display_name = display_name[:200]

    ext = path.splitext(path.basename(saved_abs_path))[1].lower() or ".webm"
    camera_fs_name = _camera_fs_dir_name(upload_key, display_name)
    match_out_dir = path.join(
        current_app.root_path,
        "..",
        "static",
        "uploads",
        "videos",
        tournament_url,
        match_obj.field,
        match_uuid,
        camera_fs_name,
    )
    os.makedirs(match_out_dir, exist_ok=True)

    final_abs_path = path.join(match_out_dir, f"source{ext}")
    saved_abs_path = path.abspath(path.normpath(saved_abs_path))
    shutil.move(saved_abs_path, final_abs_path)

    source_dir = path.dirname(saved_abs_path)
    if path.isdir(source_dir):
        try:
            shutil.rmtree(source_dir)
        except OSError:
            _log.warning(
                "direct user upload: could not remove temp dir %s",
                source_dir,
            )

    final_rel = path.join(
        "static",
        "uploads",
        "videos",
        tournament_url,
        match_obj.field,
        match_uuid,
        camera_fs_name,
        f"source{ext}",
    ).replace("\\", "/")

    camera_row = Camera(
        match_uuid=match_uuid,
        event=tournament_url,
        field=field_obj.id,
        name=display_name,
        source_type="user_upload",
        uploaded_by_user_id=uploader_user_id,
        uploaded_by_user_type=uploader_user_type,
        status="UPLOADING",
        file=final_rel,
        time_world=None,
        time_video=None,
    )
    db.session.add(camera_row)
    db.session.commit()

    def _yt_upload():
        with app_obj.app_context():
            upload_camera_to_youtube(str(camera_row.uuid))

    threading.Thread(target=_yt_upload, daemon=True).start()

    _log.info(
        "direct user upload: created camera uuid=%s match=%s",
        camera_row.uuid,
        match_uuid,
    )
    return str(camera_row.uuid)

