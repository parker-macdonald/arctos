import json
import logging
import re
from models import Match, Point, db
import os
from os import path
import subprocess
from itertools import groupby
from datetime import datetime, timezone

log = logging.getLogger(__name__)


def _chunk_timestamp_sort_key(c):
    """Return a comparable value for chunk_start_timestamp (ms float or ISO string)."""
    raw = c.get("chunk_start_timestamp")
    if raw is None:
        return 0.0
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).strip()
    if not s:
        return 0.0
    # Parse ISO 8601 (e.g. 2025-02-23T19:30:00.123Z)
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.timestamp() * 1000.0
    except (ValueError, TypeError):
        return 0.0


def _chunk_timestamp_to_iso_utc(c):
    """Return chunk_start_timestamp as ISO 8601 UTC string for stream_start_time."""
    raw = c.get("chunk_start_timestamp")
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        try:
            dt = datetime.fromtimestamp(float(raw) / 1000.0, tz=timezone.utc)
            return dt.isoformat().replace("+00:00", "Z")
        except (ValueError, OSError):
            return None
    s = str(raw).strip()
    if not s:
        return None
    if s.endswith("Z") or "+" in s or re.search(r"-\d{2}:\d{2}$", s):
        return s
    return s if s.endswith("Z") else f"{s.rstrip('zZ')}Z"


def _get_media_duration_sec(file_path, cwd=None):
    """Return duration in seconds of a media file via ffprobe, or None if unavailable."""
    if cwd:
        input_arg = path.basename(file_path)
        run_cwd = cwd
    else:
        input_arg = file_path
        run_cwd = path.dirname(path.abspath(file_path))
    args = [
        "ffprobe",
        "-i", input_arg,
        "-show_entries", "format=duration",
        "-v", "quiet", "-of", "csv=p=0",
    ]
    result = subprocess.run(
        args,
        cwd=run_cwd,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout:
        return None
    s = result.stdout.strip()
    if not s or s == "N/A":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def finalize_recording_worker(
    logger, tournament_url, field_name, match_id, camera_name, chunk_dir
):
    """
    1. Concatenate all chunks with the same session_id in order of chunk_start_timestamp using cat.
    2. Fix each joined raw file with ffmpeg (-c copy -map 0 -tag:v hvc1 -movflags +faststart for MP4).
    3. Concatenate all session outputs with the concat demuxer.
    4. Compute point_timestamps and stream_start_time (UTC) for the frontend to scrub to points.
    """
    import sys
    print(f"finalize_recording: worker started match_id={match_id} chunk_dir={chunk_dir}", flush=True)
    sys.stdout.flush()
    sys.stderr.flush()

    _log = logger or log
    chunk_dir = path.abspath(path.normpath(chunk_dir))

    first_webm = path.join(chunk_dir, "chunk_0.webm")
    first_mp4 = path.join(chunk_dir, "chunk_0.mp4")
    if not path.exists(first_webm) and not path.exists(first_mp4):
        _log.warning("finalize_recording: no chunk_0.webm or chunk_0.mp4 in %s", chunk_dir)
        return

    with open(path.join(chunk_dir, "chunks_meta.json"), "r") as f:
        all_meta = list(json.load(f).values())

    if not all_meta:
        _log.warning("finalize_recording: no chunks in chunks_meta.json")
        return

    # Group by session_id, sort each group by chunk_start_timestamp
    def session_key(x):
        return x.get("session_id") or ""

    sorted_meta = sorted(
        all_meta,
        key=lambda c: (session_key(c), _chunk_timestamp_sort_key(c)),
    )
    sessions = []
    for sid, group in groupby(sorted_meta, key=session_key):
        if not sid:
            continue
        chunks = sorted(list(group), key=_chunk_timestamp_sort_key)
        sessions.append((sid, chunks))

    sessions.sort(key=lambda s: _chunk_timestamp_sort_key(s[1][0]) if s[1] else 0.0)

    if not sessions:
        _log.warning("finalize_recording: no sessions with session_id in chunks_meta")
        return

    # Detect container from first chunk
    first_filename = sessions[0][1][0].get("filename", "")
    is_mp4 = first_filename.lower().endswith(".mp4")
    ext = "mp4" if is_mp4 else "webm"

    pts = Point.query.filter_by(match=match_id).order_by(Point.stamp.asc()).all()
    point_by_uuid = {str(pt.uuid): pt for pt in pts}

    session_outputs = []  # list of (session_id, output_basename, segment_start_sec, point_uuids_in_session)
    stream_start_iso = None  # ISO UTC of very first chunk start

    for session_id, session_chunks in sessions:
        # Only include chunks that exist on disk, in order
        ordered_chunks = [
            c for c in session_chunks
            if path.exists(path.join(chunk_dir, c["filename"]))
        ]
        if not ordered_chunks:
            _log.warning("finalize_recording: session %s has no existing chunk files", session_id)
            continue

        if stream_start_iso is None:
            stream_start_iso = _chunk_timestamp_to_iso_utc(ordered_chunks[0])

        segment_start_ms = _chunk_timestamp_sort_key(ordered_chunks[0])
        segment_start_sec = segment_start_ms / 1000.0

        # 1. Cat chunks into one raw file
        joined_raw = path.join(chunk_dir, f"joined_raw_{session_id}.{ext}")
        cat_files = [c["filename"] for c in ordered_chunks]
        try:
            with open(joined_raw, "wb") as out:
                subprocess.run(
                    ["cat"] + cat_files,
                    cwd=chunk_dir,
                    stdout=out,
                    check=True,
                )
        except (OSError, subprocess.CalledProcessError) as e:
            _log.warning("finalize_recording: session %s cat failed: %s", session_id, e)
            continue

        if not path.exists(joined_raw) or path.getsize(joined_raw) == 0:
            _log.warning("finalize_recording: session %s joined raw empty or missing", session_id)
            continue

        # 2. Fix with ffmpeg
        session_basename = f"session_{session_id}.{ext}"
        session_output_path = path.join(chunk_dir, session_basename)
        if is_mp4:
            fix_cmd = [
                "ffmpeg", "-i", path.basename(joined_raw),
                "-c", "copy", "-map", "0",
                "-tag:v", "hvc1", "-movflags", "+faststart",
                "-loglevel", "error", "-y", session_basename,
            ]
        else:
            fix_cmd = [
                "ffmpeg", "-i", path.basename(joined_raw),
                "-c", "copy", "-map", "0",
                "-loglevel", "error", "-y", session_basename,
            ]
        result = subprocess.run(
            fix_cmd,
            cwd=chunk_dir,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 or not path.exists(session_output_path) or path.getsize(session_output_path) == 0:
            _log.warning(
                "finalize_recording: session %s ffmpeg fix failed returncode=%s stderr=%s",
                session_id, result.returncode, (result.stderr or "").strip(),
            )
            if result.stderr:
                print(result.stderr.strip(), flush=True)
            continue

        point_uuids = set()
        for c in ordered_chunks:
            pid = c.get("point_id")
            if pid and str(pid).strip():
                point_uuids.add(str(pid).strip())

        session_outputs.append((session_id, session_basename, segment_start_sec, point_uuids))
        print(f"finalize_recording: session {session_id} -> {session_basename}", flush=True)

    if not session_outputs:
        _log.warning("finalize_recording: no session outputs produced")
        return

    print(f"finalize_recording: {len(session_outputs)} session(s) for concat", flush=True)

    # 3. Concat all sessions with concat demuxer
    final_basename = f"final_video.{ext}"
    final_path = path.join(chunk_dir, final_basename)
    concat_list_path = path.join(chunk_dir, "concat_sessions.txt")
    with open(concat_list_path, "w") as f:
        for _sid, basename, _start, _pids in session_outputs:
            abs_path = path.abspath(path.join(chunk_dir, basename))
            f.write(f"file {repr(abs_path)}\n")
    _log.info("finalize_recording: wrote concat_sessions.txt with %d entries", len(session_outputs))

    concat_cmd = [
        "ffmpeg", "-f", "concat", "-safe", "0",
        "-i", path.basename(concat_list_path),
        "-c", "copy",
        "-loglevel", "error", "-y", final_basename,
    ]
    result = subprocess.run(
        concat_cmd,
        cwd=chunk_dir,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not path.exists(final_path) or path.getsize(final_path) == 0:
        _log.warning(
            "finalize_recording: concat failed returncode=%s stderr=%s",
            result.returncode, (result.stderr or "").strip(),
        )
        if result.stderr:
            print(result.stderr.strip(), flush=True)
        return

    print(f"finalize_recording: wrote {final_basename}", flush=True)

    # 4. Compute point_timestamps and stream_start_time for frontend scrubbing
    try:
        segment_durations = []
        for _sid, basename, _start, _pids in session_outputs:
            seg_path = path.join(chunk_dir, basename)
            d = _get_media_duration_sec(seg_path, cwd=chunk_dir)
            if d is None or d <= 0:
                _log.warning("finalize_recording: could not get duration for %s", basename)
                d = 0.0
            segment_durations.append(d)

        video_offset = [0.0]
        for d in segment_durations:
            video_offset.append(video_offset[-1] + d)

        points_with_footage = set()
        for _sid, _basename, _start, pids in session_outputs:
            points_with_footage.update(pids)

        point_timestamps = []
        for pt in pts:
            if str(pt.uuid) not in points_with_footage:
                continue
            if pt.stamp is None or pt.end_stamp is None:
                continue
            pt_start_sec = pt.stamp.replace(tzinfo=timezone.utc).timestamp()
            segment_index = None
            for j, (_sid, _basename, seg_start_sec, pids) in enumerate(session_outputs):
                if str(pt.uuid) in pids:
                    segment_index = j
                    break
            if segment_index is None:
                continue
            seg_start_sec = session_outputs[segment_index][2]
            in_video_start = video_offset[segment_index] + (pt_start_sec - seg_start_sec)
            in_video_start = max(0.0, in_video_start)
            point_timestamps.append({
                "point_uuid": str(pt.uuid),
                "in_video_start": round(in_video_start, 3),
            })

        print(f"finalize_recording: point_timestamps (count={len(point_timestamps)})", flush=True)
        _log.info("finalize_recording: point_timestamps=%s", point_timestamps)

        video_path = path.join(
            "static", "uploads", "videos",
            tournament_url, field_name, match_id, camera_name, final_basename,
        ).replace("\\", "/")

        match = Match.query.filter_by(uuid=match_id).first()
        if not match:
            _log.error("finalize_recording: match not found uuid=%s", match_id)
        else:
            stream_starts = {}
            if match.camera_stream_starts:
                try:
                    stream_starts = json.loads(match.camera_stream_starts)
                except (TypeError, ValueError):
                    stream_starts = {}
            stream_starts[camera_name] = {
                "video_path": video_path,
                "point_timestamps": point_timestamps,
                "type": "recorded",
                "stream_start_time": stream_start_iso,
            }
            match.camera_stream_starts = json.dumps(stream_starts)
            db.session.commit()
            print(f"finalize_recording: committed camera_stream_starts for match {match_id}", flush=True)
            _log.info("finalize_recording: committed camera_stream_starts for match %s", match_id)
    except Exception as e:
        print(f"finalize_recording: ERROR after concat: {e}", flush=True)
        _log.exception("finalize_recording: failed after concat")
