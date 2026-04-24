"""
Helper functions for camera/stream management.
"""

import re
import os
import requests
from datetime import datetime, timezone
import json
import hmac
import hashlib
import base64

from flask import current_app, jsonify, request


def extract_video_id(camera_url: str | None) -> str | None:
    """Extract the YouTube video ID from a URL or bare ID string.

    Supports ``youtube.com/watch?v=``, ``youtu.be/``, ``youtube.com/embed/``,
    ``youtube.com/v/``, and bare 11-character video IDs.

    Args:
        camera_url: A YouTube URL, video ID, or ``None``.

    Returns:
        The 11-character video ID, or ``None`` if extraction fails.
    """
    if not camera_url:
        return None

    patterns = [
        r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/|youtube\.com/v/)([^&\n?#]+)",
        r"^([a-zA-Z0-9_-]{11})$",
    ]
    for pattern in patterns:
        match = re.search(pattern, camera_url)
        if match:
            return match.group(1)
    return None


def get_stream_start_time(video_id: str | None) -> str | None:
    """Fetch the actual start time of a YouTube live stream.

    Calls the YouTube Data API v3 ``videos`` endpoint using the
    ``YOUTUBE_API_KEY`` environment variable.

    Args:
        video_id: A YouTube video ID string, or ``None``.

    Returns:
        The stream start time as a UTC ISO-8601 string ending with ``"Z"``
        (e.g. ``"2024-06-01T14:30:00Z"``), or ``None`` if the API key is
        not configured, the video is not a live stream, or the request fails.
    """
    api_key = os.environ.get("YOUTUBE_API_KEY")
    if not api_key:
        return None

    try:
        url = "https://www.googleapis.com/youtube/v3/videos"
        params = {
            "id": video_id,
            "part": "liveStreamingDetails,snippet",
            "key": api_key,
        }
        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()

        if not data.get("items"):
            return None

        video = data["items"][0]
        live_details = video.get("liveStreamingDetails", {})
        actual_start_time = live_details.get("actualStartTime")

        if actual_start_time:
            # YouTube API returns actualStartTime in RFC3339 format (ISO 8601 with timezone)
            # It's always in UTC, typically ending with 'Z' or '+00:00'
            # Parse and ensure timezone-aware UTC
            # Handle both 'Z' and '+00:00' formats
            if actual_start_time.endswith("Z"):
                start_dt = datetime.fromisoformat(actual_start_time.replace("Z", "+00:00"))
            else:
                start_dt = datetime.fromisoformat(actual_start_time)

            # Ensure it's timezone-aware UTC
            if start_dt.tzinfo is None:
                # If no timezone info, assume UTC (YouTube API should always provide it, but be safe)
                start_dt = start_dt.replace(tzinfo=timezone.utc)
            else:
                # Convert to UTC if it's not already
                start_dt = start_dt.astimezone(timezone.utc)

            # Return in ISO format with 'Z' suffix for UTC
            return start_dt.isoformat().replace("+00:00", "Z")

        return None
    except Exception as e:
        print(f"Error fetching stream start time for video {video_id}: {e}")
        return None


def parse_camera_urls(camera_field_value: str | None) -> list[str]:
    """Parse a field's camera column into a list of URL strings.

    Accepts a JSON array, a JSON-encoded single URL string, or a bare URL
    string for backwards compatibility.

    Args:
        camera_field_value: The raw value of the
            :attr:`~app.models.tournament.Field.camera` column, or ``None``.

    Returns:
        List of camera URL strings.  Empty list for falsy input.
    """
    if not camera_field_value:
        return []

    try:
        # Try parsing as JSON array
        cameras = json.loads(camera_field_value)
        if isinstance(cameras, list):
            return cameras
        elif isinstance(cameras, str):
            # Single URL as JSON string
            return [cameras]
    except (json.JSONDecodeError, TypeError):
        pass

    # Fallback: treat as single URL string
    return [camera_field_value] if camera_field_value.strip() else []


def get_all_camera_stream_starts(field) -> dict[str, str]:
    """Return stream start times for every camera on a field.

    Iterates over all camera URLs on *field*, fetches each stream's actual
    start time from the YouTube Data API, and returns a mapping of
    ``camera_index (str)`` → ``ISO timestamp (str)``.  String keys are used
    to remain consistent with the JSON storage format.

    Args:
        field: A :class:`~app.models.tournament.Field` ORM instance.

    Returns:
        Dict mapping zero-based camera index (as a string) to a UTC ISO-8601
        start-time string ending with ``"Z"``.  Empty dict when the field
        has no cameras or no start times can be determined.
    """
    if not field or not field.camera:
        return {}

    camera_urls = parse_camera_urls(field.camera)
    stream_starts = {}

    for idx, camera_url in enumerate(camera_urls):
        video_id = extract_video_id(camera_url)
        if video_id:
            start_time = get_stream_start_time(video_id)
            if start_time:
                # Use string key to match JSON storage format
                stream_starts[str(idx)] = start_time

    return stream_starts


def calculate_stream_timestamp(point_stamp, stream_start_time):
    """Calculate timestamp in seconds from stream start.
    Uses the same calculation as the frontend calculateSeekTime function.

    Args:
        point_stamp: Point timestamp (datetime or ISO string)
        stream_start_time: Stream start time (ISO string)

    Returns:
        Timestamp in seconds from stream start, or None if calculation fails
    """
    if not point_stamp or not stream_start_time:
        return None


# -----------------------------
# Camera access key helpers
# -----------------------------


def generate_camera_key(tournament_url: str, field_name: str) -> str:
    """Generate a URL-safe HMAC-SHA256 access key for a field camera endpoint.

    The key is computed from the Flask ``SECRET_KEY`` and the
    ``"<tournament_url>:<field_name>"`` message, then base64url-encoded.

    Args:
        tournament_url: Tournament URL slug.
        field_name: Name of the field to generate the key for.

    Returns:
        URL-safe base64-encoded HMAC digest string (no padding ``=``).
    """
    secret = current_app.config.get("SECRET_KEY")
    if not secret:
        secret = "dev-key"
    message = f"{tournament_url}:{field_name}".encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")


def validate_camera_key(tournament_url: str, field_name: str, provided_key: str) -> bool:
    """Return whether *provided_key* is a valid camera access key for a field.

    Uses a constant-time comparison to prevent timing attacks.

    Args:
        tournament_url: Tournament URL slug.
        field_name: Name of the field.
        provided_key: The access key to validate.

    Returns:
        ``True`` if *provided_key* matches the expected HMAC digest.
    """
    expected_key = generate_camera_key(tournament_url, field_name)
    return hmac.compare_digest(expected_key, (provided_key or "").strip())


def get_camera_key_from_request() -> str | None:
    """Extract camera access key from request (query params, JSON body, or form data)."""
    key = (request.args.get("camera_key") or "").strip()
    if key:
        return key
    if request.is_json and request.json:
        key = (request.json.get("camera_key") or "").strip()
        if key:
            return key
    key = (request.form.get("camera_key") or "").strip()
    if key:
        return key
    return None


def require_camera_key(tournament_url: str, field_name: str):
    """Validate the camera access key present in the current HTTP request.

    Checks query parameters, JSON body, and form data (in that order) for
    a ``camera_key`` value and validates it against the expected HMAC digest.

    Args:
        tournament_url: Tournament URL slug.
        field_name: Name of the field whose key to validate.

    Returns:
        A ``(is_valid, error_response)`` tuple.  When valid, ``is_valid``
        is ``True`` and *error_response* is ``None``.  When invalid,
        *error_response* is a ``(jsonify_result, 403)`` tuple.
    """
    access_key = get_camera_key_from_request()
    if not access_key or not validate_camera_key(tournament_url, field_name, access_key):
        return (False, (jsonify({"error": "Invalid or missing access key"}), 403))
    return (True, None)

    try:
        # Parse point timestamp
        if isinstance(point_stamp, datetime):
            point_dt = point_stamp
            if point_dt.tzinfo is None:
                point_dt = point_dt.replace(tzinfo=timezone.utc)
        else:
            point_str = str(point_stamp)
            if not re.search(r"[zZ]|[\+\-]\d{2}:?\d{2}$", point_str):
                point_str = re.sub(r"\.\d+$", "", point_str) + "Z"
            point_dt = datetime.fromisoformat(point_str.replace("Z", "+00:00"))
            if point_dt.tzinfo is None:
                point_dt = point_dt.replace(tzinfo=timezone.utc)

        # Parse stream start time
        # Stream start time should be in ISO format, ideally with 'Z' suffix for UTC
        stream_str = str(stream_start_time)

        # Normalize to ISO format with timezone
        if stream_str.endswith("Z"):
            # Already has 'Z' suffix, convert to +00:00 for fromisoformat
            stream_dt = datetime.fromisoformat(stream_str.replace("Z", "+00:00"))
        elif re.search(r"[\+\-]\d{2}:?\d{2}$", stream_str):
            # Has timezone offset, parse directly
            stream_dt = datetime.fromisoformat(stream_str)
        else:
            # No timezone info, assume UTC and add 'Z'
            stream_str = re.sub(r"\.\d+$", "", stream_str) + "Z"
            stream_dt = datetime.fromisoformat(stream_str.replace("Z", "+00:00"))

        # Ensure it's timezone-aware UTC
        if stream_dt.tzinfo is None:
            stream_dt = stream_dt.replace(tzinfo=timezone.utc)
        else:
            # Convert to UTC if it's not already
            stream_dt = stream_dt.astimezone(timezone.utc)

        # Calculate difference in seconds
        diff = (point_dt - stream_dt).total_seconds()
        return diff if diff >= 0 else None
    except Exception as e:
        print(f"Error calculating stream timestamp: {e}")
        return None
