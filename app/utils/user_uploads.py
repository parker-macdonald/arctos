from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from os import path
from typing import Optional

from flask import current_app

from models import Camera, Field, Match, Point, Team, db
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


def user_autoclips_from_uploaded_video_worker(
    logger,
    *,
    tournament_url: str,
    field_name: str,
    match_points_padding_sec: float,
    uploader_user_id: str,
    uploader_user_type: str,
    user_video_abs_path: str,
    user_video_filename_stem: str,
    upload_group_name: str,
    video_start_world_override_iso: Optional[str] = None,
):
    """
    Create one highlight video per match overlapped by the uploaded footage.

    For each point overlapped by the uploaded video time range, generate a clip
    covering [point_start-3s, point_end+3s] (clamped), then concatenate clips
    per match.
    """
    _log = logger or current_app.logger
    user_video_abs_path = path.abspath(path.normpath(user_video_abs_path))
    if not path.exists(user_video_abs_path):
        _log.error("user_autoclips: source file missing: %s", user_video_abs_path)
        return

    video_duration_sec = _get_media_duration_sec(user_video_abs_path)
    if video_duration_sec <= 0:
        _log.error("user_autoclips: could not determine duration for %s", user_video_abs_path)
        return

    if video_start_world_override_iso:
        override_dt = _parse_iso_to_datetime_utc(video_start_world_override_iso)
        video_start_world = override_dt or _get_video_start_world_datetime(user_video_abs_path)
    else:
        video_start_world = _get_video_start_world_datetime(user_video_abs_path)
    from datetime import timedelta

    video_end_world = video_start_world + timedelta(seconds=video_duration_sec)

    field_obj = Field.query.filter_by(event=tournament_url, name=field_name).first()
    if not field_obj:
        _log.error("user_autoclips: field not found event=%s field_name=%s", tournament_url, field_name)
        return

    # Query all matches on this field in this tournament.
    matches = Match.query.filter_by(event=tournament_url, field=field_name).all()
    if not matches:
        _log.warning("user_autoclips: no matches for field=%s event=%s", field_name, tournament_url)
        return

    # Query points for all those matches once, then filter in memory.
    match_ids = [m.uuid for m in matches]
    points = Point.query.filter(Point.match.in_(match_ids)).order_by(Point.stamp.asc()).all()

    # Group points by match_uuid.
    points_by_match: dict[str, list[Point]] = {}
    for pt in points:
        if not pt.match:
            continue
        points_by_match.setdefault(pt.match, []).append(pt)

    for match_uuid, pts in points_by_match.items():
        # Build per-point clip plans (clamped to uploaded video window).
        plans = build_clip_plans_for_points(
            video_start_world=video_start_world,
            video_duration_sec=video_duration_sec,
            points=pts,
            padding_sec=match_points_padding_sec,
        )
        if not plans:
            continue

        match_obj = Match.query.filter_by(uuid=match_uuid).first()
        if not match_obj:
            continue

        # Output paths for this match highlight.
        camera_name = f"{upload_group_name}-{user_video_filename_stem}"
        match_out_dir = path.join(
            current_app.root_path,
            "..",
            "static",
            "uploads",
            "videos",
            tournament_url,
            field_name,
            match_uuid,
            camera_name,
        )
        os.makedirs(match_out_dir, exist_ok=True)

        src_clips_dir = path.join(match_out_dir, "clips")
        os.makedirs(src_clips_dir, exist_ok=True)

        clip_paths: list[str] = []
        time_world: list[str] = []
        time_video: list[float] = []

        concat_offset = 0.0
        for i, plan in enumerate(plans):
            clip_name = f"point_clip_{i}.webm"
            clip_abs_path = path.join(src_clips_dir, clip_name)
            _ffmpeg_trim_to_webm(
                input_path=user_video_abs_path,
                start_sec=plan.clip_start_file_sec,
                end_sec=plan.clip_end_file_sec,
                output_path=clip_abs_path,
            )
            clip_paths.append(clip_abs_path)

            # in-highlight time for the point's real start.
            point_start_in_highlight = concat_offset + plan.point_start_in_clip_sec
            time_world.append(_dt_to_iso_z(plan.point_start_world))
            time_video.append(round(point_start_in_highlight, 3))

            concat_offset += max(0.0, plan.clip_end_file_sec - plan.clip_start_file_sec)

        # Concatenate per match.
        final_highlight_abs_path = path.join(match_out_dir, "final_video.webm")
        _ffmpeg_concat_webm(clip_paths=clip_paths, output_path=final_highlight_abs_path)

        # Camera row file path should be static-relative.
        final_highlight_rel = path.join(
            "static",
            "uploads",
            "videos",
            tournament_url,
            field_name,
            match_uuid,
            camera_name,
            "final_video.webm",
        ).replace("\\", "/")

        camera_row = Camera(
            match_uuid=match_uuid,
            event=tournament_url,
            field=field_obj.id,
            name=camera_name,
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

        # Kick off YouTube upload in a background thread.
        import threading

        app_obj = current_app._get_current_object()

        def _yt_upload():
            with app_obj.app_context():
                upload_camera_to_youtube(str(camera_row.uuid))

        threading.Thread(target=_yt_upload, daemon=True).start()

        _log.info(
            "user_autoclips: created camera uuid=%s match=%s points=%d",
            camera_row.uuid,
            match_uuid,
            len(plans),
        )

