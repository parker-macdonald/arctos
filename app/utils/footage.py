import json
import logging
import math
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

    For WebM (Firefox MediaRecorder): concatenate chunk bytes verbatim — no fMP4 stripping.

    - fMP4: Write the first chunk verbatim; strip duplicate ftyp+moov on following chunks.
    - WebM: Write all parts verbatim.
    """
    chunk_dir = path.abspath(chunk_dir)
    if not ordered_chunks:
        return False
    try:
        first_fn = ordered_chunks[0]["filename"]
        if first_fn.lower().endswith(".webm"):
            with open(joined_raw, "wb") as out:
                for c in ordered_chunks:
                    fp = path.join(chunk_dir, c["filename"])
                    with open(fp, "rb") as f:
                        out.write(f.read())
            return True
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


def _epoch_ms_to_iso_utc(ms: float) -> str:
    """ISO 8601 UTC string from epoch milliseconds."""
    try:
        dt = datetime.fromtimestamp(float(ms) / 1000.0, tz=timezone.utc)
        return dt.isoformat().replace("+00:00", "Z")
    except (ValueError, OSError, OverflowError, TypeError):
        return ""


def _ffmpeg_repair_concat_for_probe(
    in_basename: str, out_basename: str, cwd: str, _log
) -> bool:
    """
    Raw browser fMP4 byte-concats are often not a timeline ffprobe can walk. Remux with
    ffmpeg (-c copy) so streams get a coherent PTS/DTS map; output is suitable for probe + trim.
    """
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-fflags",
        "+genpts+igndts",
        "-i",
        in_basename,
        "-c",
        "copy",
        "-map",
        "0",
        "-avoid_negative_ts",
        "make_zero",
        "-y",
        out_basename,
    ]
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        _log.warning(
            "finalize_recording: repair remux failed %s -> %s rc=%s stderr=%s",
            in_basename,
            out_basename,
            result.returncode,
            (result.stderr or "").strip()[:1500],
        )
        return False
    out_path = path.join(cwd, out_basename)
    if not path.exists(out_path) or path.getsize(out_path) == 0:
        return False
    return True


def _parse_ffprobe_keyframe_frames_csv(stdout: str) -> float | None:
    """First video keyframe time from -show_frames csv (pkt_pts_time, pict_type, key_frame)."""
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2:
            continue
        pts_s = parts[0]
        pict = parts[1] if len(parts) > 1 else ""
        kf = parts[2] if len(parts) > 2 else ""
        is_kf = kf == "1"
        if not is_kf and pict:
            is_kf = pict.upper() in ("I", "I0", "IDR") or pict == "1"
        if not is_kf:
            continue
        if pts_s in ("", "N/A", "nan"):
            continue
        try:
            t = float(pts_s)
            if math.isfinite(t) and t >= 0:
                return t
        except (TypeError, ValueError):
            continue
    return None


def _parse_ffprobe_keyframe_packets_csv(stdout: str) -> float | None:
    """First keyframe packet time from -show_packets (pts_time + flags containing K)."""
    for line in stdout.splitlines():
        line = line.strip()
        if not line or line.startswith(";"):
            continue
        parts = [p.strip() for p in line.split(",")]
        if parts and parts[0] == "packet":
            parts = parts[1:]
        if len(parts) < 2:
            continue
        pts_s = parts[0]
        flags = parts[1] if len(parts) > 1 else ""
        if "K" not in flags and "key" not in flags.lower():
            continue
        if pts_s in ("", "N/A", "nan"):
            continue
        try:
            t = float(pts_s)
            if math.isfinite(t) and t >= 0:
                return t
        except (TypeError, ValueError):
            continue
    return None


def _ffprobe_first_keyframe_pts_sec(rel_path: str, cwd: str | None, _log) -> float | None:
    """
    Media timeline position (seconds) of the first video keyframe.
    Tries frame metadata, then packet flags. Uses read_intervals 0+60 first, then full file.
    Prefer calling this on a file produced by _ffmpeg_repair_concat_for_probe, not raw cat output.
    """
    full = path.join(cwd, rel_path) if cwd else path.abspath(rel_path)

    def run_frames(extra: list) -> float | None:
        args = [
            "ffprobe",
            "-v",
            "error",
            *extra,
            "-select_streams",
            "v:0",
            "-show_frames",
            "-show_entries",
            "frame=pkt_pts_time,pict_type,key_frame",
            "-of",
            "csv=p=0",
            full,
        ]
        result = subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout:
            return _parse_ffprobe_keyframe_frames_csv(result.stdout)
        return None

    def run_packets(extra: list) -> float | None:
        args = [
            "ffprobe",
            "-v",
            "error",
            *extra,
            "-select_streams",
            "v:0",
            "-show_packets",
            "-show_entries",
            "packet=pts_time,flags",
            "-of",
            "csv=p=0",
            full,
        ]
        result = subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout:
            return _parse_ffprobe_keyframe_packets_csv(result.stdout)
        return None

    for extra in (["-read_intervals", "0+60"], []):
        t = run_frames(extra)
        if t is not None:
            return t
        t = run_packets(extra)
        if t is not None:
            return t
    return None


def _ffmpeg_trim_and_remux_session(
    joined_basename: str,
    out_basename: str,
    cwd: str,
    trim_start_sec: float,
    video_codec: str | None,
    _log,
) -> bool:
    """
    Trim leading samples from a muxed fMP4 (stream copy from first keyframe time) and
    remux with faststart + codec tag for broad player support.
    """
    tag_args: list = []
    if video_codec == "hevc":
        tag_args = ["-tag:v", "hvc1"]
    elif video_codec in ("h264", "avc1"):
        tag_args = ["-tag:v", "avc1"]

    trim_start_sec = max(0.0, float(trim_start_sec or 0.0))
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
    ]
    if trim_start_sec > 1e-6:
        cmd.extend(["-ss", str(trim_start_sec)])
    cmd.extend(
        [
            "-i",
            joined_basename,
            "-c",
            "copy",
            "-map",
            "0",
            "-avoid_negative_ts",
            "make_zero",
            *tag_args,
        ]
    )
    if out_basename.lower().endswith(".mp4"):
        cmd.extend(["-movflags", "+faststart"])
    cmd.extend(["-y", out_basename])
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        _log.warning(
            "finalize_recording: trim+remux failed returncode=%s stderr=%s",
            result.returncode,
            (result.stderr or "").strip()[:2000],
        )
        return False
    out_path = path.join(cwd, out_basename)
    if not path.exists(out_path) or path.getsize(out_path) == 0:
        return False
    return True


def _ffmpeg_final_concat_timestamps(
    chunk_dir: str,
    concat_list_basename: str,
    final_basename: str,
    _log,
) -> bool:
    """
    Concatenate session outputs with the concat demuxer, then remux so generated PTS
    and stream alignment are well-behaved (-c copy). MP4 gets faststart; WebM skips movflags.
    """
    sfx = path.splitext(final_basename)[1].lstrip(".") or "mp4"
    stage_basename = f"final_concat_stage.{sfx}"
    stage_path = path.join(chunk_dir, stage_basename)
    final_path = path.join(chunk_dir, final_basename)

    concat_cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        concat_list_basename,
        "-c",
        "copy",
        "-y",
        stage_basename,
    ]
    result = subprocess.run(
        concat_cmd,
        cwd=chunk_dir,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        _log.warning(
            "finalize_recording: concat demuxer failed returncode=%s stderr=%s",
            result.returncode,
            (result.stderr or "").strip()[:2000],
        )
        return False
    if not path.exists(stage_path) or path.getsize(stage_path) == 0:
        return False

    remux_cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-fflags",
        "+genpts+igndts",
        "-i",
        stage_basename,
        "-c",
        "copy",
        "-map",
        "0",
        "-reset_timestamps",
        "1",
        "-avoid_negative_ts",
        "make_zero",
    ]
    if final_basename.lower().endswith(".mp4"):
        remux_cmd.extend(["-movflags", "+faststart"])
    remux_cmd.extend(["-y", final_basename])
    result = subprocess.run(
        remux_cmd,
        cwd=chunk_dir,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0 and path.exists(final_path) and path.getsize(final_path) > 0:
        try:
            os.remove(stage_path)
        except OSError:
            pass
        return True

    _log.warning(
        "finalize_recording: post-concat timestamp remux failed stderr=%s",
        (result.stderr or "").strip()[:2000],
    )
    if path.exists(stage_path) and path.getsize(stage_path) > 0:
        try:
            if path.exists(final_path):
                os.remove(final_path)
            os.rename(stage_path, final_path)
            _log.warning(
                "finalize_recording: using concat-only output (timestamp remux skipped)"
            )
            return True
        except OSError as e:
            _log.warning("finalize_recording: could not fall back to concat-only: %s", e)
    return False


def finalize_recording_worker(
    logger, tournament_url, field_name, match_id, camera_name, chunk_dir
):
    """
    1. Group chunks by session_id; sort by blob_event_timestamp_ms (else chunk_start).
    2. Per session: byte-concat fMP4 fragments, ffprobe first video keyframe time, ffmpeg
       stream-copy trim from that keyframe (+movflags faststart, codec tag) for a playable file.
    3. Wall-clock segment anchors use first-chunk epoch start + keyframe media offset (trim).
    4. Concatenate session MP4s with ffmpeg concat demuxer, then remux (genpts, reset_timestamps)
       for clean multi-session timestamps.
    5. Compute point_timestamps, stream_start_time, time_world / time_video for scrubbing.
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

    pts = Point.query.filter_by(match=match_id).order_by(Point.stamp.asc()).all()
    # Snapshot points and release the ORM session before long ffmpeg work so SQLite is not
    # held open (avoids "database is locked" for concurrent request handlers).
    pts_rows = [
        {"uuid": str(pt.uuid), "stamp": pt.stamp, "end_stamp": pt.end_stamp}
        for pt in pts
    ]
    db.session.remove()

    # list of (session_id, output_basename, wall_first_kf_sec, session_start_iso)
    # wall_first_kf_sec = UTC epoch seconds for the first video keyframe kept after trim (for points / interpolation).
    session_outputs = []
    stream_start_iso = None  # ISO UTC of first keyframe in the first session (whole output timeline)
    final_output_ext = "mp4"  # first successful session sets this (mp4 vs webm)

    for session_id, session_chunks in sessions:
        ordered_chunks = [
            c
            for c in session_chunks
            if path.exists(path.join(chunk_dir, c["filename"]))
        ]
        if not ordered_chunks:
            _log.warning(
                "finalize_recording: session %s has no existing chunk files", session_id
            )
            continue

        earliest_chunk = min(ordered_chunks, key=_chunk_sort_key)
        is_webm = ordered_chunks[0]["filename"].lower().endswith(".webm")
        ext = "webm" if is_webm else "mp4"
        if is_webm:
            concat_chunks = sorted(ordered_chunks, key=_chunk_sort_key)
        else:
            concat_chunks = _reorder_session_chunks_ftyp_first(ordered_chunks, chunk_dir)
        joined_basename = f"joined_raw_{session_id}.{ext}"
        joined_raw = path.join(chunk_dir, joined_basename)
        if not _cat_session_chunks(concat_chunks, chunk_dir, joined_raw, _log, session_id):
            continue

        if not path.exists(joined_raw) or path.getsize(joined_raw) == 0:
            _log.warning(
                "finalize_recording: session %s joined raw empty or missing", session_id
            )
            continue

        # ffprobe on raw byte-concats is unreliable; remux first so timeline / packets exist.
        repaired_basename = f"joined_repaired_{session_id}.{ext}"
        repaired_path = path.join(chunk_dir, repaired_basename)
        trim_source_basename = joined_basename
        if _ffmpeg_repair_concat_for_probe(
            joined_basename, repaired_basename, chunk_dir, _log
        ):
            trim_source_basename = repaired_basename
            video_codec = _get_video_codec(repaired_path, chunk_dir)
            t_kf = _ffprobe_first_keyframe_pts_sec(repaired_basename, chunk_dir, _log)
        else:
            _log.warning(
                "finalize_recording: session %s repair remux failed; probing/trimming raw concat",
                session_id,
            )
            video_codec = _get_video_codec(joined_raw, chunk_dir)
            t_kf = _ffprobe_first_keyframe_pts_sec(joined_basename, chunk_dir, _log)

        if t_kf is None:
            _log.info(
                "finalize_recording: session %s no keyframe time from ffprobe; trim=0",
                session_id,
            )
            t_kf = 0.0

        earliest_ms = _chunk_timestamp_sort_key(earliest_chunk)
        # Wall time of first retained keyframe: chunk timeline starts at earliest_ms; first KF at +t_kf s.
        wall_first_kf_sec = earliest_ms / 1000.0 + t_kf

        session_start_iso = _epoch_ms_to_iso_utc(
            wall_first_kf_sec * 1000.0
        ) or _chunk_timestamp_to_iso_utc(
            {"chunk_start_timestamp": wall_first_kf_sec * 1000.0}
        )

        if stream_start_iso is None:
            stream_start_iso = session_start_iso

        session_basename = f"session_{session_id}.{ext}"
        session_output_path = path.join(chunk_dir, session_basename)
        if not _ffmpeg_trim_and_remux_session(
            trim_source_basename,
            session_basename,
            chunk_dir,
            t_kf,
            video_codec,
            _log,
        ):
            _log.warning(
                "finalize_recording: session %s trim+remux failed", session_id
            )
            if path.exists(repaired_path):
                try:
                    os.remove(repaired_path)
                except OSError:
                    pass
            continue

        if path.exists(repaired_path):
            try:
                os.remove(repaired_path)
            except OSError:
                pass

        if not path.exists(session_output_path) or path.getsize(session_output_path) == 0:
            _log.warning(
                "finalize_recording: session %s output missing or empty", session_id
            )
            continue

        if not session_outputs:
            final_output_ext = ext

        session_outputs.append(
            (session_id, session_basename, wall_first_kf_sec, session_start_iso)
        )
        _log.info(
            "finalize_recording: session %s -> %s trim_media_sec=%.4f wall_first_kf=%s",
            session_id,
            session_basename,
            t_kf,
            session_start_iso,
        )
        print(f"finalize_recording: session {session_id} -> {session_basename}", flush=True)

    if not session_outputs:
        _log.warning("finalize_recording: no session outputs produced")
        return

    print(f"finalize_recording: {len(session_outputs)} session(s) for concat", flush=True)

    final_basename = f"final_video.{final_output_ext}"
    final_path = path.join(chunk_dir, final_basename)
    concat_list_path = path.join(chunk_dir, "concat_sessions.txt")
    with open(concat_list_path, "w") as f:
        for _sid, basename, _start, _session_start_iso in session_outputs:
            abs_path = path.abspath(path.join(chunk_dir, basename))
            f.write(f"file {repr(abs_path)}\n")
    _log.info(
        "finalize_recording: wrote concat_sessions.txt with %d entries", len(session_outputs)
    )

    if not _ffmpeg_final_concat_timestamps(
        chunk_dir, path.basename(concat_list_path), final_basename, _log
    ):
        _log.warning("finalize_recording: final concat / timestamp pass failed")
        return

    if not path.exists(final_path) or path.getsize(final_path) == 0:
        _log.warning("finalize_recording: final output missing or empty")
        return
    print(f"finalize_recording: wrote {final_basename}", flush=True)

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
