import json
import logging
import re
from models import Match, Point, Field, Camera, db
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


def _chunk_sort_key(c):
    """Prefer BlobEvent timeStamp (ms) for ordering; else chunk_start_timestamp."""
    raw = c.get("blob_event_timestamp_ms")
    if raw is not None:
        try:
            return float(raw)
        except (TypeError, ValueError):
            pass
    return _chunk_timestamp_sort_key(c)


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


def _top_level_box_spans(data: bytes):
    """Yield (fourcc, start_byte, end_exclusive) for each top-level ISO BMFF box."""
    i = 0
    n = len(data)
    while i + 8 <= n:
        sz = int.from_bytes(data[i : i + 4], "big")
        if sz < 8:
            break
        typ = data[i + 4 : i + 8]
        end = i + sz
        if end > n:
            break
        yield (typ, i, end)
        i = end


def _strip_leading_init_segment(data: bytes) -> bytes:
    """
    MediaRecorder often emits a full fMP4 per timeslice: [ftyp][moov][moof][mdat]...
    Concatenating those repeats moov and breaks ffmpeg (trun/tfhd errors).
    For fragments after the first, drop leading ftyp+moov if present.
    Pure [moof][mdat] fragments are returned unchanged.
    """
    spans = list(_top_level_box_spans(data))
    if not spans:
        return data
    idx = 0
    if spans[idx][0] == b"ftyp":
        idx += 1
    else:
        return data
    if idx < len(spans) and spans[idx][0] == b"moov":
        idx += 1
    else:
        return data
    if idx >= len(spans):
        return b""
    start = spans[idx][1]
    return data[start:]


def _chunk_file_starts_with_ftyp(chunk_dir: str, filename: str) -> bool:
    fp = path.join(chunk_dir, filename)
    try:
        with open(fp, "rb") as f:
            head = f.read(12)
        return len(head) >= 8 and head[4:8] == b"ftyp"
    except OSError:
        return False


def _reorder_session_chunks_ftyp_first(chunks, chunk_dir):
    """
    Put a chunk that begins with an ftyp box first (init segment), then others by _chunk_sort_key.
    If none start with ftyp, preserve sort order by _chunk_sort_key only.
    """
    return sorted(
        chunks,
        key=lambda c: (
            0 if _chunk_file_starts_with_ftyp(chunk_dir, c["filename"]) else 1,
            _chunk_sort_key(c),
        ),
    )


def _cat_session_chunks(ordered_chunks, chunk_dir, joined_raw, _log, session_id):
    """
    Concatenate fMP4 fragments for one recording session.

    `ordered_chunks` must already be ordered with a chunk that starts with ftyp (init) first
    (see _reorder_session_chunks_ftyp_first).

    - Write the first chunk verbatim.
    - For following chunks, strip leading ftyp+moov when present (duplicate init per
      MediaRecorder timeslice); keep pure moof+mdat fragments as-is.
    """
    chunk_dir = path.abspath(chunk_dir)
    if not ordered_chunks:
        return False
    try:
        first_fn = ordered_chunks[0]["filename"]
        if not _chunk_file_starts_with_ftyp(chunk_dir, first_fn):
            _log.warning(
                "finalize_recording: session %s first chunk %s does not start with "
                "ftyp; joined file may be unreadable (missing moov).",
                session_id,
                first_fn,
            )
        with open(joined_raw, "wb") as out:
            for i, c in enumerate(ordered_chunks):
                fp = path.join(chunk_dir, c["filename"])
                with open(fp, "rb") as f:
                    data = f.read()
                if i == 0:
                    preview = data[:16].hex() if data else ""
                    _log.info(
                        "finalize_recording: session %s concat[0] %s bytes=%s head16=%s",
                        session_id,
                        c["filename"],
                        len(data),
                        preview,
                    )
                    out.write(data)
                else:
                    stripped = _strip_leading_init_segment(data)
                    out.write(stripped)
        return True
    except OSError as e:
        _log.warning("finalize_recording: session %s concat failed: %s", session_id, e)
        return False


def _get_video_codec(file_path, cwd):
    """Return video codec name (hevc, h264, avc1) or None if unavailable."""
    if cwd:
        input_arg = path.basename(file_path)
        run_cwd = cwd
    else:
        input_arg = file_path
        run_cwd = path.dirname(path.abspath(file_path))
    args = [
        "ffprobe",
        "-i", input_arg,
        "-select_streams", "v:0",
        "-show_entries", "stream=codec_name",
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
    return result.stdout.strip().lower() or None


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
    1. Group chunks by session_id; within each session sort by blob_event_timestamp_ms (else chunk_start).
       Concatenate chunk files with cat.
    2. Remux each session cat output with ffmpeg (-c copy, -movflags +faststart for MP4).
    3. Concatenate session MP4s with ffmpeg concat demuxer (-c copy).
    4. Compute point_timestamps and stream_start_time (UTC) for the frontend to scrub to points.
    """
    import sys
    print(f"finalize_recording: worker started match_id={match_id} chunk_dir={chunk_dir}", flush=True)
    sys.stdout.flush()
    sys.stderr.flush()

    _log = logger or log
    chunk_dir = path.abspath(path.normpath(chunk_dir))

    chunks_meta_path = path.join(chunk_dir, "chunks_meta.json")
    if not path.exists(chunks_meta_path):
        _log.warning("finalize_recording: missing chunks_meta.json in %s", chunk_dir)
        return

    with open(chunks_meta_path, "r") as f:
        all_meta = list(json.load(f).values())

    if not all_meta:
        _log.warning("finalize_recording: no chunks in chunks_meta.json")
        return

    # Group by session_id, sort each group by chunk_start_timestamp
    def session_key(x):
        return x.get("session_id") or ""

    sorted_meta = sorted(
        all_meta,
        key=lambda c: (session_key(c), _chunk_sort_key(c)),
    )
    sessions = []
    for sid, group in groupby(sorted_meta, key=session_key):
        if not sid:
            continue
        chunks = sorted(list(group), key=_chunk_sort_key)
        sessions.append((sid, chunks))

    sessions.sort(key=lambda s: _chunk_sort_key(s[1][0]) if s[1] else 0.0)

    if not sessions:
        _log.warning("finalize_recording: no sessions with session_id in chunks_meta")
        return

    ext = "mp4"

    pts = Point.query.filter_by(match=match_id).order_by(Point.stamp.asc()).all()
    # Snapshot points and release the ORM session before long ffmpeg work so SQLite is not
    # held open (avoids "database is locked" for concurrent request handlers).
    pts_rows = [
        {"uuid": str(pt.uuid), "stamp": pt.stamp, "end_stamp": pt.end_stamp}
        for pt in pts
    ]
    db.session.remove()

    # list of (session_id, output_basename, segment_start_sec, session_start_iso)
    session_outputs = []
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

        # Chronological first chunk (metadata / points). Concat order may differ (ftyp init first).
        earliest_chunk = min(ordered_chunks, key=_chunk_sort_key)

        if stream_start_iso is None:
            stream_start_iso = _chunk_timestamp_to_iso_utc(earliest_chunk)

        # Recording session start timestamp (world time alignment) used for interpolation.
        # If missing, fall back to chunk_start_timestamp.
        rec_session_start_raw = earliest_chunk.get("recording_session_start_time")
        if rec_session_start_raw is None:
            rec_session_start_raw = earliest_chunk.get("chunk_start_timestamp")
        session_start_iso = _chunk_timestamp_to_iso_utc(
            {"chunk_start_timestamp": rec_session_start_raw}
        )

        # Wall-clock segment start for point_timestamps (chunk_start_timestamp is epoch ms; blob_event is not).
        segment_start_ms = _chunk_timestamp_sort_key(earliest_chunk)
        segment_start_sec = segment_start_ms / 1000.0

        concat_chunks = _reorder_session_chunks_ftyp_first(ordered_chunks, chunk_dir)

        joined_raw = path.join(chunk_dir, f"joined_raw_{session_id}.{ext}")
        if not _cat_session_chunks(concat_chunks, chunk_dir, joined_raw, _log, session_id):
            continue

        if not path.exists(joined_raw) or path.getsize(joined_raw) == 0:
            _log.warning("finalize_recording: session %s joined raw empty or missing", session_id)
            continue

        # Remux cat output (validates/repairs fMP4; faststart for streaming)
        session_basename = f"session_{session_id}.{ext}"
        session_output_path = path.join(chunk_dir, session_basename)
        video_codec = _get_video_codec(joined_raw, chunk_dir)
        tag_args = []
        if video_codec == "hevc":
            tag_args = ["-tag:v", "hvc1"]
        elif video_codec in ("h264", "avc1"):
            tag_args = ["-tag:v", "avc1"]
        fix_cmd = [
            "ffmpeg", "-i", path.basename(joined_raw),
            "-c", "copy", "-map", "0",
            *tag_args,
            "-movflags", "+faststart",
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

        session_outputs.append(
            (session_id, session_basename, segment_start_sec, session_start_iso)
        )
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
        for _sid, basename, _start, _session_start_iso in session_outputs:
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

    # Some browser/webm muxers produce streams whose timestamps are not well-behaved when
    # concatenated via -c copy. YouTube can interpret these incorrectly (e.g. playing too fast).
    # Fix by remuxing with regenerated PTS and resetting timestamps. This is not a re-encode
    # (still -c copy); it should only repair container timing metadata.
    remux_fixed_basename = f"final_video_fixed.{ext}"
    remux_fixed_path = path.join(chunk_dir, remux_fixed_basename)
    remux_cmd = [
        "ffmpeg",
        "-fflags",
        "+genpts",
        "-i",
        path.basename(final_path),
        "-c",
        "copy",
        "-map",
        "0",
        "-reset_timestamps",
        "1",
        "-loglevel",
        "error",
        "-y",
        remux_fixed_basename,
    ]
    result = subprocess.run(
        remux_cmd,
        cwd=chunk_dir,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0 and path.exists(remux_fixed_path) and path.getsize(remux_fixed_path) > 0:
        try:
            os.remove(final_path)
        except OSError:
            pass
        final_basename = remux_fixed_basename
        final_path = remux_fixed_path
        print(f"finalize_recording: wrote {final_basename} (timestamp-fixed)", flush=True)
    else:
        print(f"finalize_recording: wrote {final_basename} (no timestamp fix); stderr={((result.stderr or '').strip() or 'n/a')}", flush=True)

    # 4. Compute point_timestamps and stream_start_time for frontend scrubbing
    try:
        segment_durations = []
        for _sid, basename, _start, _session_start_iso in session_outputs:
            seg_path = path.join(chunk_dir, basename)
            d = _get_media_duration_sec(seg_path, cwd=chunk_dir)
            if d is None or d <= 0:
                _log.warning("finalize_recording: could not get duration for %s", basename)
                d = 0.0
            segment_durations.append(d)

        video_offset = [0.0]
        for d in segment_durations:
            video_offset.append(video_offset[-1] + d)

        # Interpolation arrays for matching world timestamps to in-video seconds.
        # One entry per recording session (concatenated segment start).
        time_world = [s[3] for s in session_outputs]
        time_video = video_offset[:-1]

        # Point timestamps from session start times and point.stamp only (no point_id from chunks).
        stream_start_sec = session_outputs[0][2] if session_outputs else 0.0
        stream_end_sec = stream_start_sec + sum(segment_durations)

        point_timestamps = []
        for pt in pts_rows:
            if pt["stamp"] is None or pt["end_stamp"] is None:
                continue
            pt_start_sec = pt["stamp"].replace(tzinfo=timezone.utc).timestamp()
            if pt_start_sec < stream_start_sec or pt_start_sec >= stream_end_sec:
                continue
            # Find segment j that contains pt_start_sec
            segment_index = None
            for j, (_sid, _basename, seg_start_sec, _session_start_iso) in enumerate(
                session_outputs
            ):
                seg_end_sec = seg_start_sec + (
                    segment_durations[j]
                    if j < len(segment_durations)
                    else 0.0
                )
                if seg_start_sec <= pt_start_sec < seg_end_sec:
                    segment_index = j
                    break
            if segment_index is None:
                continue
            seg_start_sec = session_outputs[segment_index][2]
            in_video_start = video_offset[segment_index] + (pt_start_sec - seg_start_sec)
            in_video_start = max(0.0, in_video_start)
            point_timestamps.append({
                "point_uuid": pt["uuid"],
                "in_video_start": round(in_video_start, 3),
            })

        print(f"finalize_recording: point_timestamps (count={len(point_timestamps)})", flush=True)
        _log.info("finalize_recording: point_timestamps=%s", point_timestamps)

        from flask import current_app
        video_path = path.join(
            "static",
            "uploads",
            "videos",
            tournament_url,
            field_name,
            match_id,
            camera_name,
            final_basename,
        ).replace("\\", "/")

        stream_starts = {}
        match = Match.query.filter_by(uuid=match_id).first()
        if not match:
            _log.error("finalize_recording: match not found uuid=%s", match_id)
        elif video_path:
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
            print(
                f"finalize_recording: committed camera_stream_starts for match {match_id}",
                flush=True,
            )
            _log.info(
                "finalize_recording: committed camera_stream_starts for match %s", match_id
            )

        # 3. Create a match-scoped camera row for the final video.
        # The YouTube upload worker (implemented elsewhere) will transition UPLOADING -> SUCCESS/FAILED.
        try:
            field_obj = Field.query.filter_by(
                event=tournament_url, name=field_name
            ).first()
            if field_obj and video_path:
                camera_row = Camera(
                    match_uuid=match_id,
                    event=tournament_url,
                    field=field_obj.id,
                    name=camera_name,
                    source_type="recording",
                    status="UPLOADING",
                    file=video_path,
                    time_world=json.dumps(time_world),
                    time_video=json.dumps(time_video),
                )
                db.session.add(camera_row)
                db.session.commit()

                _log.info(
                    "finalize_recording: created camera row uuid=%s match=%s camera=%s",
                    camera_row.uuid,
                    match_id,
                    camera_name,
                )

                import threading

                app_obj = current_app._get_current_object()

                def _yt_upload():
                    with app_obj.app_context():
                        from app.utils.youtube_upload import upload_camera_to_youtube

                        upload_camera_to_youtube(str(camera_row.uuid))

                threading.Thread(target=_yt_upload, daemon=True).start()
        except Exception as e:
            _log.exception("finalize_recording: failed to create/upload camera row: %s", e)
        if False:
            # Delete all chunks and intermediate files
            to_remove = []
            for c in all_meta:
                fn = c.get("filename")
                if fn:
                    to_remove.append(path.join(chunk_dir, fn))
            to_remove.append(path.join(chunk_dir, "chunks_meta.json"))
            for sid, _basename, _start, _session_start_iso in session_outputs:
                to_remove.append(path.join(chunk_dir, f"joined_raw_{sid}.{ext}"))
            for _sid, basename, _start, _session_start_iso in session_outputs:
                to_remove.append(path.join(chunk_dir, basename))
            to_remove.append(path.join(chunk_dir, "concat_sessions.txt"))
            for fp in to_remove:
                try:
                    if path.exists(fp):
                        os.remove(fp)
                        _log.debug("finalize_recording: removed %s", fp)
                except OSError as e:
                    _log.warning("finalize_recording: could not remove %s: %s", fp, e)
            print(f"finalize_recording: deleted {len(to_remove)} chunk/intermediate file(s)", flush=True)
    except Exception as e:
        print(f"finalize_recording: ERROR after concat: {e}", flush=True)
        _log.exception("finalize_recording: failed after concat")
