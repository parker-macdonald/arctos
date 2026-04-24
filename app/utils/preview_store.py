"""
Filesystem-backed store for camera preview state (requested, pending frames, serving).
Works with multiple gunicorn workers when they share the same filesystem.
"""

import json
import os
import time
import shutil


# Default: sibling to app root (e.g. project/preview/)
def _preview_root() -> str:
    """Return the absolute path to the preview data root directory."""
    from flask import current_app

    return os.path.abspath(os.path.join(current_app.root_path, "..", "preview"))


def _safe_join(base: str, *parts: str) -> str | None:
    """Join path components and verify the result stays under *base*.

    Args:
        base: The allowed root directory (absolute path).
        *parts: Path components to append.

    Returns:
        Absolute resolved path, or ``None`` if the result would escape *base*.
    """
    path = os.path.normpath(os.path.join(base, *parts))
    if not path.startswith(base):
        return None
    return path


def requested_path(tournament: str, field: str) -> str:
    """Return the filesystem path of the preview-requested sentinel file.

    Args:
        tournament: Tournament URL slug (sanitised to alphanumeric / ``_-``).
        field: Field name (sanitised).

    Returns:
        Absolute path under the preview root ``requested/`` directory.
    """
    root = _preview_root()
    # Sanitize: no path traversal
    t = "".join(c for c in tournament if c.isalnum() or c in "_-")
    f = "".join(c for c in field if c.isalnum() or c in "_-")
    return os.path.join(root, "requested", t, f)


def pending_path(tournament: str, field: str, camera_name: str) -> str:
    """Return the filesystem path for a pending (un-promoted) preview JPEG.

    Args:
        tournament: Tournament URL slug.
        field: Field name.
        camera_name: Camera identifier string.

    Returns:
        Absolute path under the preview root ``pending/`` directory.
    """
    root = _preview_root()
    t = "".join(c for c in tournament if c.isalnum() or c in "_-")
    f = "".join(c for c in field if c.isalnum() or c in "_-")
    cam = "".join(c for c in camera_name if c.isalnum() or c in "_-") or "camera"
    return os.path.join(root, "pending", t, f, f"{cam}.jpg")


def serving_path(tournament: str, field: str, camera_name: str) -> str:
    """Return the filesystem path for a promoted (serving) preview JPEG.

    Args:
        tournament: Tournament URL slug.
        field: Field name.
        camera_name: Camera identifier string.

    Returns:
        Absolute path under the preview root ``serving/`` directory.
    """
    root = _preview_root()
    t = "".join(c for c in tournament if c.isalnum() or c in "_-")
    f = "".join(c for c in field if c.isalnum() or c in "_-")
    cam = "".join(c for c in camera_name if c.isalnum() or c in "_-") or "camera"
    return os.path.join(root, "serving", t, f, f"{cam}.jpg")


def metadata_path(tournament: str, field: str, camera_name: str) -> str:
    """Return the filesystem path for a camera's device metadata JSON file.

    Args:
        tournament: Tournament URL slug.
        field: Field name.
        camera_name: Camera identifier string.

    Returns:
        Absolute path under the preview root ``meta/`` directory.
    """
    root = _preview_root()
    t = "".join(c for c in tournament if c.isalnum() or c in "_-")
    f = "".join(c for c in field if c.isalnum() or c in "_-")
    cam = "".join(c for c in camera_name if c.isalnum() or c in "_-") or "camera"
    return os.path.join(root, "meta", t, f, f"{cam}.json")


def ensure_dir(path: str) -> None:
    """Create all directories leading to *path*, ignoring existing dirs.

    Args:
        path: A file path whose parent directories should be created.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)


def is_preview_requested(tournament: str, field: str) -> bool:
    """Return whether a preview has been requested for this field.

    Args:
        tournament: Tournament URL slug.
        field: Field name.

    Returns:
        ``True`` if the sentinel file exists on disk.
    """
    p = requested_path(tournament, field)
    return os.path.isfile(p)


def set_preview_requested(tournament: str, field: str) -> None:
    """Write a sentinel file indicating a preview is requested.

    Args:
        tournament: Tournament URL slug.
        field: Field name.
    """
    p = requested_path(tournament, field)
    ensure_dir(p)
    with open(p, "w") as f:
        f.write(str(time.time()))


def clear_preview_requested(tournament: str, field: str) -> None:
    """Remove the preview sentinel file and delete cached frame data.

    Also removes the ``pending/`` and ``serving/`` directories for this
    field so stale frames are not served after the preview session ends.

    Args:
        tournament: Tournament URL slug.
        field: Field name.
    """
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
    """Write a raw JPEG frame to the pending (staging) location.

    Args:
        tournament: Tournament URL slug.
        field: Field name.
        camera_name: Camera identifier.
        data: Raw JPEG bytes to write.
    """
    p = pending_path(tournament, field, camera_name)
    ensure_dir(p)
    with open(p, "wb") as f:
        f.write(data)


def has_pending(tournament: str, field: str, camera_name: str) -> bool:
    """Return whether a pending frame file exists for the camera.

    Args:
        tournament: Tournament URL slug.
        field: Field name.
        camera_name: Camera identifier.

    Returns:
        ``True`` if the pending JPEG file exists on disk.
    """
    return os.path.isfile(pending_path(tournament, field, camera_name))


def move_pending_to_serving(tournament: str, field: str, camera_name: str) -> bool:
    """Atomically promote the pending frame to the serving location.

    Args:
        tournament: Tournament URL slug.
        field: Field name.
        camera_name: Camera identifier.

    Returns:
        ``True`` if the file was moved; ``False`` if no pending file existed.
    """
    pa = pending_path(tournament, field, camera_name)
    pb = serving_path(tournament, field, camera_name)
    if not os.path.isfile(pa):
        return False
    ensure_dir(pb)
    shutil.move(pa, pb)
    return True


def read_serving(tournament: str, field: str, camera_name: str):
    """Read the serving JPEG frame for a camera.

    Args:
        tournament: Tournament URL slug.
        field: Field name.
        camera_name: Camera identifier.

    Returns:
        A ``(bytes, mtime)`` tuple where *mtime* is the file's modification
        time (Unix timestamp float); or ``(None, None)`` when the file does
        not exist.
    """
    p = serving_path(tournament, field, camera_name)
    if not os.path.isfile(p):
        return None, None
    with open(p, "rb") as f:
        data = f.read()
    return data, os.path.getmtime(p)


# Max age for "recent" camera (seconds). Cameras with no file or stale file drop off the list.
RECENT_MTIME_SEC = 90


def list_cameras_with_recent_frame(tournament: str, field: str) -> list[str]:
    """Return cameras that have a frame file written within the last 90 seconds.

    Searches both ``pending/`` and ``serving/`` directories.

    Args:
        tournament: Tournament URL slug.
        field: Field name.

    Returns:
        Sorted list of camera name strings with a recently modified JPEG.
    """
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


def serving_mtime(tournament: str, field: str, camera_name: str) -> float:
    """Return the modification time of the serving frame file.

    Args:
        tournament: Tournament URL slug.
        field: Field name.
        camera_name: Camera identifier.

    Returns:
        Unix timestamp float, or ``0`` when the file does not exist or an
        OS error occurs.
    """
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
    """Persist device metadata for a camera to a JSON file.

    Args:
        tournament: Tournament URL slug.
        field: Field name.
        camera_name: Camera identifier.
        storage_usage: Storage used in bytes, or ``None``.
        storage_quota: Storage capacity in bytes, or ``None``.
        battery_level: Battery level as a ``0.0``–``1.0`` fraction, or
            ``None``.
    """
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
    """Read persisted device metadata for a camera.

    Args:
        tournament: Tournament URL slug.
        field: Field name.
        camera_name: Camera identifier.

    Returns:
        A dict with keys ``storage_usage``, ``storage_quota``,
        ``battery_level``, ``updated`` (Unix timestamp), or ``None`` when
        the file does not exist or cannot be parsed.
    """
    p = metadata_path(tournament, field, camera_name)
    if not os.path.isfile(p):
        return None
    try:
        with open(p) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
