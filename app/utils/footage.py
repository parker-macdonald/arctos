import json
from models import Match, Point, db
from os import path, listdir, remove
import subprocess
from itertools import groupby
from datetime import datetime, timezone


def finalize_recording_worker(
    logger, tournament_url, field_name, match_id, camera_name, chunk_dir
):
    # Use absolute normalized path so ffmpeg and list files work regardless of worker cwd
    chunk_dir = path.abspath(path.normpath(chunk_dir))
    # Check if first chunk exists
    first_chunk_path = path.join(chunk_dir, "chunk_0.webm")
    if not path.exists(first_chunk_path):
        return

    with open(path.join(chunk_dir, "chunks_meta.json"), "r") as f:
        all_meta = list(json.load(f).values())

    if not all_meta:
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
        return

    # Sort sessions by first chunk's start time
    sessions.sort(key=lambda s: s[1][0]["chunk_start_timestamp"])

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
        # 1. Binary-concatenate chunks in order. Skip the first chunk if it doesn't start with WebM
        #    EBML header (some browsers / wasm MediaRecorder send continuation first, init second).
        session_chunks = sorted(session_chunks, key=lambda c: c["chunk_start_timestamp"])
        raw_name = raw_basename(session_id)
        raw_path = path.join(chunk_dir, raw_name)
        try:
            with open(raw_path, "wb") as out:
                for i, c in enumerate(session_chunks):
                    chunk_path = path.join(chunk_dir, c["filename"])
                    if not path.exists(chunk_path):
                        continue
                    with open(chunk_path, "rb") as inp:
                        data = inp.read()
                    if i == 0 and len(data) >= 4 and data[:4] != EBML_MAGIC:
                        if logger:
                            logger.info(
                                "finalize_recording: session %s skipping first chunk (no EBML header)",
                                session_id,
                            )
                        continue
                    out.write(data)
        except OSError as e:
            if logger:
                logger.warning("finalize_recording: session %s binary concat failed: %s", session_id, e)
            continue
        if not path.exists(raw_path) or path.getsize(raw_path) == 0:
            if logger:
                logger.warning("finalize_recording: session %s produced empty raw file", session_id)
            continue

        segment_start_ms = min(c["chunk_start_timestamp"] for c in session_chunks)
        segment_start_sec = segment_start_ms / 1000.0

        # Point IDs that appear in this session (non-empty)
        point_ids_in_session = set()
        for c in session_chunks:
            pid = c.get("point_id")
            if pid and str(pid).strip():
                point_ids_in_session.add(str(pid).strip())

        # Clip end: 5 seconds after the end of the last point in this segment
        if point_ids_in_session:
            last_end_ts = None
            for pid in point_ids_in_session:
                if pid not in point_by_uuid:
                    continue
                pt = point_by_uuid[pid]
                end_ts = pt.end_stamp.replace(tzinfo=timezone.utc).timestamp()
                if last_end_ts is None or end_ts > last_end_ts:
                    last_end_ts = end_ts
            if last_end_ts is not None:
                clip_end_sec = (last_end_ts - segment_start_sec) + EXTRA_TAIL_SEC
            else:
                clip_end_sec = None  # use full duration
        else:
            clip_end_sec = None

        if clip_end_sec is not None:
            # Get raw duration to cap clip_end_sec (run in chunk_dir so path has no spaces)
            probe = subprocess.run(
                [
                    "ffprobe",
                    "-i", raw_name,
                    "-show_entries", "format=duration",
                    "-v", "quiet", "-of", "csv=p=0",
                ],
                capture_output=True,
                text=True,
                cwd=chunk_dir,
            )
            raw_duration = (
                float(probe.stdout.strip())
                if probe.returncode == 0 and probe.stdout.strip()
                else 0.0
            )
            clip_end_sec = (
                min(clip_end_sec, raw_duration) if raw_duration > 0 else raw_duration
            )

        segment_name = segment_basename(session_id)
        # Re-encode to VP9 and optionally trim to clip_end_sec (cwd=chunk_dir).
        # Force -f webm so binary-concatenated MediaRecorder output is read as one stream.
        cmd = [
            "ffmpeg", "-f", "webm", "-i", raw_name,
            "-c:v", "libvpx-vp9", "-crf", "16", "-b:v", "0",
            "-c:a", "libopus",
            "-fflags", "+genpts", "-avoid_negative_ts", "make_zero",
            "-loglevel", "error", "-y", segment_name,
        ]
        if clip_end_sec is not None and clip_end_sec > 0:
            idx = cmd.index(raw_name) + 1
            cmd = cmd[:idx] + ["-t", str(clip_end_sec)] + cmd[idx:]
        subprocess.run(cmd, cwd=chunk_dir)

        segment_path = path.join(chunk_dir, segment_name)
        if path.exists(segment_path):
            segment_files.append((segment_path, segment_start_sec, point_ids_in_session))

    # 2. Concatenate all segment files and build in_video_times (relative names, cwd=chunk_dir)
    clips_txt = path.join(chunk_dir, "clips.txt")
    with open(clips_txt, "w") as f:
        for seg_path, _, _ in segment_files:
            if path.exists(seg_path):
                print(f"file {repr(path.basename(seg_path))}", file=f)

    if segment_files:
        subprocess.run(
            [
                "ffmpeg",
                "-f", "concat", "-safe", "0",
                "-i", "clips.txt",
                "-c", "copy", "-map", "0",
                "-y", "final_video.webm",
            ],
            cwd=chunk_dir,
        )

    # Build in_video_times: [ (point_uuid, cumulative_end_sec), ... ]
    points_with_footage = set()
    for _, _, pids in segment_files:
        points_with_footage.update(pids)

    in_video_times = [[None, 0.01]]
    for pt in pts:
        if str(pt.uuid) not in points_with_footage:
            continue
        pt_start = pt.stamp.replace(tzinfo=timezone.utc).timestamp()
        pt_end = pt.end_stamp.replace(tzinfo=timezone.utc).timestamp()
        duration = max(0.0, pt_end - pt_start)
        in_video_times[-1][0] = pt.uuid
        in_video_times.append([None, in_video_times[-1][1] + duration])

    with open(path.join(chunk_dir, "metadata.json"), "r") as f:
        metadata = json.load(f)

    # for debug visibility
    metadata["point_timestamps"] = [i[1] for i in in_video_times]
    with open(path.join(chunk_dir, "metadata.json"), "w") as f:
        json.dump(metadata, f)

    print(f"match id: {match_id}")
    match = Match.query.filter_by(uuid=match_id).first()
    stream_starts = (
        json.loads(match.camera_stream_starts) if match.camera_stream_starts else dict()
    )
    print(f"STREAM STARTS: {stream_starts}")
    stream_starts[camera_name] = {
        "video_path": path.join(
            "uploads/videos",
            tournament_url,
            field_name,
            match_id,
            camera_name,
            "final_video.webm",
        ),
        "point_timestamps": [i[1] for i in in_video_times],
        "type": "recorded",
    }
    match.camera_stream_starts = json.dumps(stream_starts)
    db.session.commit()

    # Cleanup: remove chunks, session raw/segment files, and clips.txt; keep final_video and metadata.
    for file in listdir(chunk_dir):
        if file == "final_video.webm" or file == "metadata.json":
            continue
        remove(path.join(chunk_dir, file))
