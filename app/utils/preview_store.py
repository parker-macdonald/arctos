"""
Filesystem-backed store for camera preview state (requested, pending frames, serving).
Works with multiple gunicorn workers when they share the same filesystem.
"""

import json
import os
import time
import shutil
from pathlib import Path


# Default: sibling to app root (e.g. project/preview/)
def _preview_root():
    from flask import current_app
    return os.path.abspath(
        os.path.join(current_app.root_path, "..", "preview")
    )


def _safe_join(base, *parts):
    """Join and resolve; ensure result is under base."""
    path = os.path.normpath(os.path.join(base, *parts))
    if not path.startswith(base):
        return None
    return path


def requested_path(tournament: str, field: str) -> str:
    root = _preview_root()
    # Sanitize: no path traversal
    t = "".join(c for c in tournament if c.isalnum() or c in "_-")
    f = "".join(c for c in field if c.isalnum() or c in "_-")
    return os.path.join(root, "requested", t, f)


def pending_path(tournament: str, field: str, camera_name: str) -> str:
    root = _preview_root()
    t = "".join(c for c in tournament if c.isalnum() or c in "_-")
    f = "".join(c for c in field if c.isalnum() or c in "_-")
    cam = "".join(c for c in camera_name if c.isalnum() or c in "_-") or "camera"
    return os.path.join(root, "pending", t, f, f"{cam}.jpg")


def serving_path(tournament: str, field: str, camera_name: str) -> str:
    root = _preview_root()
    t = "".join(c for c in tournament if c.isalnum() or c in "_-")
    f = "".join(c for c in field if c.isalnum() or c in "_-")
    cam = "".join(c for c in camera_name if c.isalnum() or c in "_-") or "camera"
    return os.path.join(root, "serving", t, f, f"{cam}.jpg")


def metadata_path(tournament: str, field: str, camera_name: str) -> str:
    root = _preview_root()
    t = "".join(c for c in tournament if c.isalnum() or c in "_-")
    f = "".join(c for c in field if c.isalnum() or c in "_-")
    cam = "".join(c for c in camera_name if c.isalnum() or c in "_-") or "camera"
    return os.path.join(root, "meta", t, f, f"{cam}.json")


def ensure_dir(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)


def is_preview_requested(tournament: str, field: str) -> bool:
    p = requested_path(tournament, field)
    return os.path.isfile(p)


def set_preview_requested(tournament: str, field: str) -> None:
    p = requested_path(tournament, field)
    ensure_dir(p)
    with open(p, "w") as f:
        f.write(str(time.time()))


def clear_preview_requested(tournament: str, field: str) -> None:
    p = requested_path(tournament, field)
    if os.path.isfile(p):
        os.remove(p)
    # Optionally delete pending/serving for this field
    root = _preview_root()
    t = "".join(c for c in tournament if c.isalnum() or c in "_-")
    f = "".join(c for c in field if c.isalnum() or c in "_-")
    for sub in ("pending", "serving"):
        dir_path = os.path.join(root, sub, t, f)
        if os.path.isdir(dir_path):
            try:
                shutil.rmtree(dir_path)
            except OSError:
                pass


def write_pending(tournament: str, field: str, camera_name: str, data: bytes) -> None:
    p = pending_path(tournament, field, camera_name)
    ensure_dir(p)
    with open(p, "wb") as f:
        f.write(data)


def has_pending(tournament: str, field: str, camera_name: str) -> bool:
    return os.path.isfile(pending_path(tournament, field, camera_name))


def move_pending_to_serving(tournament: str, field: str, camera_name: str) -> bool:
    pa = pending_path(tournament, field, camera_name)
    pb = serving_path(tournament, field, camera_name)
    if not os.path.isfile(pa):
        return False
    ensure_dir(pb)
    shutil.move(pa, pb)
    return True


def read_serving(tournament: str, field: str, camera_name: str):
    """Return (bytes, mtime) or (None, None)."""
    p = serving_path(tournament, field, camera_name)
    if not os.path.isfile(p):
        return None, None
    with open(p, "rb") as f:
        data = f.read()
    return data, os.path.getmtime(p)


# Max age for "recent" camera (seconds). Cameras with no file or stale file drop off the list.
RECENT_MTIME_SEC = 90


def list_cameras_with_recent_frame(tournament: str, field: str):
    """Return list of camera_name that have a recent file at pending or serving."""
    root = _preview_root()
    t = "".join(c for c in tournament if c.isalnum() or c in "_-")
    f = "".join(c for c in field if c.isalnum() or c in "_-")
    now = time.time()
    cameras = set()
    for sub in ("pending", "serving"):
        dir_path = os.path.join(root, sub, t, f)
        if not os.path.isdir(dir_path):
            continue
        for name in os.listdir(dir_path):
            if name.endswith(".jpg"):
                cam = name[:-4]
                path = os.path.join(dir_path, name)
                try:
                    if now - os.path.getmtime(path) <= RECENT_MTIME_SEC:
                        cameras.add(cam)
                except OSError:
                    pass
    return sorted(cameras)


def serving_mtime(tournament: str, field: str, camera_name: str):
    """Return mtime of serving file or 0."""
    p = serving_path(tournament, field, camera_name)
    if not os.path.isfile(p):
        return 0
    try:
        return os.path.getmtime(p)
    except OSError:
        return 0


def write_metadata(
    tournament: str,
    field: str,
    camera_name: str,
    storage_usage: float | None,
    storage_quota: float | None,
    battery_level: float | None,
) -> None:
    """Write device metadata (storage, battery) for this camera. Values in bytes or 0–1 for battery."""
    p = metadata_path(tournament, field, camera_name)
    ensure_dir(p)
    data = {
        "storage_usage": storage_usage,
        "storage_quota": storage_quota,
        "battery_level": battery_level,
        "updated": time.time(),
    }
    with open(p, "w") as f:
        json.dump(data, f)


def read_metadata(tournament: str, field: str, camera_name: str) -> dict | None:
    """Return metadata dict (storage_usage, storage_quota, battery_level, updated) or None."""
    p = metadata_path(tournament, field, camera_name)
    if not os.path.isfile(p):
        return None
    try:
        with open(p) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
