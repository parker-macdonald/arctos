import json
import logging
from models import Match, Point, db
from os import path, listdir, remove
import subprocess
from itertools import groupby
from datetime import datetime, timezone

log = logging.getLogger(__name__)


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
        timeout=30,
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
    import sys
    print(f"finalize_recording: worker started match_id={match_id} chunk_dir={chunk_dir}", flush=True)
    sys.stdout.flush()
    sys.stderr.flush()

    # Use module logger so output is visible when worker runs in a thread; fall back to print.
    _log = logger or log
    # Use absolute normalized path so ffmpeg and list files work regardless of worker cwd
    chunk_dir = path.abspath(path.normpath(chunk_dir))
    # Check if first chunk exists (webm or mp4)
    first_webm = path.join(chunk_dir, "chunk_0.webm")
    first_mp4 = path.join(chunk_dir, "chunk_0.mp4")
    if not path.exists(first_webm) and not path.exists(first_mp4):
        print(f"finalize_recording: early exit - no chunk_0.webm or chunk_0.mp4 in {chunk_dir}", flush=True)
        _log.warning("finalize_recording: no chunk_0.webm or chunk_0.mp4 in %s", chunk_dir)
        return

    with open(path.join(chunk_dir, "chunks_meta.json"), "r") as f:
        all_meta = list(json.load(f).values())

    if not all_meta:
        print("finalize_recording: early exit - no chunks in chunks_meta.json", flush=True)
        _log.warning("finalize_recording: no chunks in chunks_meta.json")
        return

    # Group chunks by session_id, sort each group by chunk_start_timestamp (ms)
    def session_key(x):
        return x.get("session_id") or ""

    sorted_meta = sorted(
        all_meta, key=lambda c: (c.get("session_id") or "", c["chunk_start_timestamp"])
    )
    sessions = []
    for sid, group in groupby(sorted_meta, key=session_key):
        if not sid:
            continue
        chunks = list(group)
        sessions.append((sid, sorted(chunks, key=lambda c: c["chunk_start_timestamp"])))

    if not sessions:
        print("finalize_recording: early exit - no sessions with session_id", flush=True)
        _log.warning("finalize_recording: no sessions with session_id in chunks_meta")
        return

    # Sort sessions by first chunk's start time
    sessions.sort(key=lambda s: s[1][0]["chunk_start_timestamp"])
    print(f"finalize_recording: {len(sessions)} session(s), {len(all_meta)} chunks total", flush=True)
    _log.info("finalize_recording: %d session(s), %d chunks", len(sessions), len(all_meta))

    pts = Point.query.filter_by(match=match_id).order_by(Point.stamp.asc()).all()
    point_by_uuid = {str(pt.uuid): pt for pt in pts}

    segment_files = (
        []
    )  # (segment_path, segment_start_sec, clip_end_sec, point_ids_in_segment)
    EXTRA_TAIL_SEC = 5.0

    raw_basename = lambda sid: f"session_{sid}_raw.webm"
    segment_basename = lambda sid: f"session_{sid}_segment.webm"

    EBML_MAGIC = bytes([0x1A, 0x45, 0xDF, 0xA3])

    for session_id, session_chunks in sessions:
        session_chunks = sorted(session_chunks, key=lambda c: c["chunk_start_timestamp"])
        n_chunks = len(session_chunks)
        print(f"finalize_recording: processing session {session_id} ({n_chunks} chunks)")
        _log.info("finalize_recording: processing session %s (%d chunks)", session_id, n_chunks)

        try:
            # Detect container from first chunk filename
            first_filename = session_chunks[0]["filename"] if session_chunks else ""
            is_mp4 = first_filename.lower().endswith(".mp4")

            if is_mp4:
                # MP4: concat with ffmpeg concat demuxer, then re-encode to WebM
                concat_list_path = path.join(chunk_dir, f"session_{session_id}_concat_list.txt")
                with open(concat_list_path, "w") as f:
                    for c in session_chunks:
                        chunk_path = path.join(chunk_dir, c["filename"])
                        if path.exists(chunk_path):
                            # Paths in list file are relative to list file dir
                            print(f"file {repr(path.basename(c['filename']))}", file=f)
                raw_name = f"session_{session_id}_raw.mp4"
                raw_path = path.join(chunk_dir, raw_name)
                concat_result = subprocess.run(
                    [
                        "ffmpeg", "-f", "concat", "-safe", "0",
                        "-i", path.basename(concat_list_path),
                        "-c", "copy", "-loglevel", "error", "-y", raw_name,
                    ],
                    cwd=chunk_dir,
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
                if concat_result.returncode != 0 or not path.exists(raw_path) or path.getsize(raw_path) == 0:
                    _log.warning(
                        "finalize_recording: session %s mp4 concat failed returncode=%s stderr=%s",
                        session_id, concat_result.returncode, (concat_result.stderr or "").strip(),
                    )
                    continue
                print(f"finalize_recording: session {session_id} wrote raw mp4 ({path.getsize(raw_path)} bytes)")
                raw_input_fmt = "mov"
                raw_input_name = raw_name
                included_chunks = session_chunks  # for segment_start_ms / point_ids below
            else:
                # WebM: drop chunks before first EBML header, then binary concat
                first_valid_index = None
                for i, c in enumerate(session_chunks):
                    chunk_path = path.join(chunk_dir, c["filename"])
                    if not path.exists(chunk_path):
                        continue
                    with open(chunk_path, "rb") as inp:
                        data = inp.read()
                    if len(data) >= 4 and data[:4] == EBML_MAGIC:
                        first_valid_index = i
                        break
                if first_valid_index is None:
                    print(f"finalize_recording: session {session_id} has no chunk with EBML header, skipping")
                    _log.warning(
                        "finalize_recording: session %s has no chunk with EBML header, skipping",
                        session_id,
                    )
                    continue
                included_chunks = session_chunks[first_valid_index:]
                if first_valid_index > 0:
                    print(f"finalize_recording: session {session_id} dropping {first_valid_index} chunk(s) before first EBML")
                    _log.info(
                        "finalize_recording: session %s dropping %d chunk(s) before first EBML",
                        session_id,
                        first_valid_index,
                    )

                raw_name = raw_basename(session_id)
                raw_path = path.join(chunk_dir, raw_name)
                try:
                    with open(raw_path, "wb") as out:
                        for c in included_chunks:
                            chunk_path = path.join(chunk_dir, c["filename"])
                            if not path.exists(chunk_path):
                                continue
                            with open(chunk_path, "rb") as inp:
                                out.write(inp.read())
                except OSError as e:
                    _log.warning("finalize_recording: session %s binary concat failed: %s", session_id, e)
                    continue
                if not path.exists(raw_path) or path.getsize(raw_path) == 0:
                    _log.warning("finalize_recording: session %s produced empty raw file", session_id)
                    continue

                print(f"finalize_recording: session {session_id} wrote raw webm ({path.getsize(raw_path)} bytes)")
                raw_input_fmt = "webm"
                raw_input_name = raw_name

            segment_start_ms = included_chunks[0]["chunk_start_timestamp"]
            segment_start_sec = segment_start_ms / 1000.0

            # Point IDs that appear in this session (from included chunks only)
            point_ids_in_session = set()
            for c in included_chunks:
                pid = c.get("point_id")
                if pid and str(pid).strip():
                    point_ids_in_session.add(str(pid).strip())

            # Clip end: 5 seconds after the end of the last point in this segment
            clip_end_sec = None
            if point_ids_in_session:
                last_end_ts = None
                for pid in point_ids_in_session:
                    if pid not in point_by_uuid:
                        continue
                    pt = point_by_uuid[pid]
                    if pt.end_stamp is None:
                        continue
                    end_ts = pt.end_stamp.replace(tzinfo=timezone.utc).timestamp()
                    if last_end_ts is None or end_ts > last_end_ts:
                        last_end_ts = end_ts
                if last_end_ts is not None:
                    clip_end_sec = (last_end_ts - segment_start_sec) + EXTRA_TAIL_SEC
            else:
                clip_end_sec = None

            if clip_end_sec is not None and clip_end_sec > 0:
                # Get raw duration to cap clip_end_sec (run in chunk_dir so path has no spaces).
                # ffprobe may return N/A for concatenated WebM; treat as unknown and don't cap.
                print(f"finalize_recording: session {session_id} running ffprobe...")
                probe = subprocess.run(
                    [
                        "ffprobe",
                        "-i", raw_input_name,
                        "-show_entries", "format=duration",
                        "-v", "quiet", "-of", "csv=p=0",
                    ],
                    capture_output=True,
                    text=True,
                    cwd=chunk_dir,
                    timeout=30,
                )
                raw_duration = None
                if probe.returncode == 0 and probe.stdout:
                    s = probe.stdout.strip()
                    if s and s != "N/A":
                        try:
                            raw_duration = float(s)
                        except ValueError:
                            pass
                if raw_duration is not None and raw_duration > 0:
                    clip_end_sec = min(clip_end_sec, raw_duration)

            segment_name = segment_basename(session_id)
            # Re-encode to WebM (VP9/Opus) and optionally trim to clip_end_sec (cwd=chunk_dir).
            print(f"finalize_recording: session {session_id} running ffmpeg...")
            cmd = [
                "ffmpeg", "-f", raw_input_fmt, "-i", raw_input_name,
                "-c:v", "libvpx-vp9", "-crf", "16", "-b:v", "0",
                "-c:a", "libopus",
                "-fflags", "+genpts", "-avoid_negative_ts", "make_zero",
                "-loglevel", "error", "-y", segment_name,
            ]
            if clip_end_sec is not None and clip_end_sec > 0:
                idx = cmd.index(raw_input_name) + 1
                cmd = cmd[:idx] + ["-t", str(clip_end_sec)] + cmd[idx:]
            result = subprocess.run(cmd, cwd=chunk_dir, capture_output=True, text=True, timeout=600)

            segment_path = path.join(chunk_dir, segment_name)
            if path.exists(segment_path) and path.getsize(segment_path) > 0:
                segment_files.append((segment_path, segment_start_sec, point_ids_in_session))
                print(f"finalize_recording: wrote {segment_name} for session {session_id}")
            else:
                print(f"finalize_recording: session {session_id} ffmpeg failed or produced no output (returncode={result.returncode})")
                _log.warning(
                    "finalize_recording: session %s ffmpeg returncode=%s stderr=%s",
                    session_id,
                    result.returncode,
                    (result.stderr or "").strip() or "(none)",
                )
                if result.stderr:
                    print(result.stderr.strip())
        except Exception as e:
            print(f"finalize_recording: session {session_id} failed: {e}")
            _log.exception("finalize_recording: session %s failed", session_id)
            continue

    # 2. Concatenate all segment files and build in_video_times (relative names, cwd=chunk_dir)
    clips_txt = path.join(chunk_dir, "clips.txt")
    with open(clips_txt, "w") as f:
        for seg_path, _, _ in segment_files:
            if path.exists(seg_path):
                print(f"file {repr(path.basename(seg_path))}", file=f)

    if segment_files:
        # Re-encode (do not use -c copy): concat+copy produces WebM with broken
        # duration/timestamps that browsers reject as "corrupted"; VLC plays it.
        # Re-encoding yields a single Segment with correct duration and cues.
        subprocess.run(
            [
                "ffmpeg",
                "-f", "concat", "-safe", "0",
                "-i", "clips.txt",
                "-c:v", "libvpx-vp9", "-crf", "16", "-b:v", "0",
                "-c:a", "libopus",
                "-fflags", "+genpts", "-avoid_negative_ts", "make_zero",
                "-loglevel", "error", "-y", "final_video.webm",
            ],
            cwd=chunk_dir,
            timeout=900,
        )

    print("finalize_recording: building point_timestamps (in-video start times)...", flush=True)
    try:
        # --- Algorithm: in-video start time for each point ---
        # The final video is a concatenation of segment files. Each segment has a world-time start
        # (segment_start_sec) and a duration. For each point we need: at what second in the final
        # video does this point start?
        #
        # 1. Get duration of each segment file (so we know how much video time each segment occupies).
        # 2. Video offset for segment j = sum of durations of segments 0..j-1.
        # 3. For each point (in match order) that has footage and is completed (has end_stamp):
        #    - Find which segment contains this point (point's uuid in that segment's point_ids).
        #    - Point in-video start = segment_video_offset + (point_start_world_sec - segment_start_world_sec).

        segment_durations = []
        for seg_path, _, _ in segment_files:
            d = _get_media_duration_sec(seg_path, cwd=chunk_dir)
            if d is None or d <= 0:
                _log.warning("finalize_recording: could not get duration for %s", path.basename(seg_path))
                d = 0.0
            segment_durations.append(d)
        video_offset = [0.0]
        for d in segment_durations:
            video_offset.append(video_offset[-1] + d)

        points_with_footage = set()
        for _, _, pids in segment_files:
            points_with_footage.update(pids)

        point_timestamps = []
        for pt in pts:
            if str(pt.uuid) not in points_with_footage:
                continue
            if pt.stamp is None or pt.end_stamp is None:
                continue
            pt_start_sec = pt.stamp.replace(tzinfo=timezone.utc).timestamp()
            # Find segment index j that contains this point
            segment_index = None
            for j, (_, seg_start_sec, pids) in enumerate(segment_files):
                if str(pt.uuid) in pids:
                    segment_index = j
                    break
            if segment_index is None:
                continue
            seg_start_sec = segment_files[segment_index][1]
            in_video_start = video_offset[segment_index] + (pt_start_sec - seg_start_sec)
            in_video_start = max(0.0, in_video_start)
            point_timestamps.append({
                "point_uuid": str(pt.uuid),
                "in_video_start": round(in_video_start, 3),
            })

        print(f"finalize_recording: point_timestamps (by uuid): {point_timestamps}", flush=True)
        _log.info("finalize_recording: point_timestamps=%s", point_timestamps)

        metadata_path = path.join(chunk_dir, "metadata.json")
        if path.exists(metadata_path):
            with open(metadata_path, "r") as f:
                metadata = json.load(f)
            metadata["point_timestamps"] = point_timestamps
            with open(metadata_path, "w") as f:
                json.dump(metadata, f)

        print(f"finalize_recording: match id: {match_id}", flush=True)
        match = Match.query.filter_by(uuid=match_id).first()
        if not match:
            print(f"finalize_recording: ERROR match not found uuid={match_id}", flush=True)
            _log.error("finalize_recording: match not found uuid=%s", match_id)
        else:
            stream_starts = (
                json.loads(match.camera_stream_starts)
                if match.camera_stream_starts
                else dict()
            )
            print(f"finalize_recording: STREAM STARTS before: {stream_starts}", flush=True)
            stream_starts[camera_name] = {
                "video_path": path.join(
                    "static",
                    "uploads",
                    "videos",
                    tournament_url,
                    field_name,
                    match_id,
                    camera_name,
                    "final_video.webm",
                ).replace("\\", "/"),
                "point_timestamps": point_timestamps,
                "type": "recorded",
            }
            match.camera_stream_starts = json.dumps(stream_starts)
            db.session.commit()
            print(f"finalize_recording: committed camera_stream_starts for match {match_id}", flush=True)
            _log.info("finalize_recording: committed camera_stream_starts for match %s", match_id)
    except Exception as e:
        print(f"finalize_recording: ERROR after ffmpeg: {e}", flush=True)
        _log.exception("finalize_recording: failed after ffmpeg")

    # Cleanup: remove chunks, raw files; keep final_video, metadata.json, and per-session segment files.
    for file in listdir(chunk_dir):
        if file in ("final_video.webm", "metadata.json", "chunks_meta.json", "clips.txt"):
            continue
        if file.startswith("session_") and file.endswith("_segment.webm"):
            continue
        remove(path.join(chunk_dir, file))
