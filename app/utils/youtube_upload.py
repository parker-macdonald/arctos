"""
YouTube upload helpers for match cameras.

This uses YouTube Data API v3 resumable uploads via `requests`.
Credentials are provided via an OAuth refresh token for a Google OAuth client.

Environment variables:
- YOUTUBE_UPLOAD_REFRESH_TOKEN (required)
- GOOGLE_CLIENT_ID (re-used if YOUTUBE_UPLOAD_CLIENT_ID not set)
- GOOGLE_CLIENT_SECRET (re-used if YOUTUBE_UPLOAD_CLIENT_SECRET not set)
- YOUTUBE_UPLOAD_PRIVACY_STATUS (optional; default: unlisted)
- YOUTUBE_UPLOAD_CATEGORY_ID (optional; default: 22)
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from os import path
from typing import Optional

import requests

from flask import current_app

from models import Camera, Match, Field, Team, db


YOUTUBE_TOKEN_URL = "https://oauth2.googleapis.com/token"
YOUTUBE_UPLOAD_INIT_URL = (
    "https://www.googleapis.com/upload/youtube/v3/videos"
)


@dataclass(frozen=True)
class YouTubeUploadConfig:
    refresh_token: str
    client_id: str
    client_secret: str
    privacy_status: str
    category_id: str


def _get_config() -> Optional[YouTubeUploadConfig]:
    refresh_token = os.environ.get("YOUTUBE_UPLOAD_REFRESH_TOKEN", "").strip()
    if not refresh_token:
        return None

    client_id = os.environ.get("YOUTUBE_UPLOAD_CLIENT_ID", "").strip()
    if not client_id:
        client_id = os.environ.get("GOOGLE_CLIENT_ID", "").strip()

    client_secret = os.environ.get("YOUTUBE_UPLOAD_CLIENT_SECRET", "").strip()
    if not client_secret:
        client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()

    if not client_id or not client_secret:
        return None

    privacy_status = os.environ.get("YOUTUBE_UPLOAD_PRIVACY_STATUS", "unlisted").strip()
    if not privacy_status:
        privacy_status = "unlisted"

    category_id = os.environ.get("YOUTUBE_UPLOAD_CATEGORY_ID", "22").strip()
    if not category_id:
        category_id = "22"

    return YouTubeUploadConfig(
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        privacy_status=privacy_status,
        category_id=category_id,
    )


def _get_access_token(cfg: YouTubeUploadConfig) -> str:
    resp = requests.post(
        YOUTUBE_TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": cfg.refresh_token,
            "client_id": cfg.client_id,
            "client_secret": cfg.client_secret,
        },
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    token = data.get("access_token")
    if not token:
        raise RuntimeError(f"Token response missing access_token: {data}")
    return token


def _video_file_abs_path(camera: Camera) -> str:
    """
    `camera.file` is stored like: static/uploads/videos/<...>/<filename>
    Flask's app root_path is /.../app, so actual static path is /.../static.
    """
    if not camera.file:
        raise RuntimeError("Camera missing file path")
    return path.normpath(path.join(current_app.root_path, "..", camera.file))


def _build_camera_title(camera: Camera) -> str:
    match = Match.query.filter_by(uuid=camera.match_uuid).first()
    if not match:
        return camera.name

    team1_name = None
    team2_name = None
    if match.team1:
        t1 = Team.query.get(match.team1)
        if t1:
            team1_name = t1.name
    if match.team2:
        t2 = Team.query.get(match.team2)
        if t2:
            team2_name = t2.name

    field_obj = Field.query.get(camera.field)
    field_name = field_obj.name if field_obj else str(camera.field)

    # Title format required by spec.
    t1 = team1_name or str(match.team1) or "T1"
    t2 = team2_name or str(match.team2) or "T2"
    return f"{match.name}: {t1} vs {t2} ({camera.name} on {field_name})"


def _youtube_init_request(
    session: requests.Session,
    access_token: str,
    file_size: int,
    content_type: str,
    title: str,
    cfg: YouTubeUploadConfig,
) -> str:
    params = {"uploadType": "resumable", "part": "snippet,status"}
    headers = {
        "Authorization": f"Bearer {access_token}",
        "X-Upload-Content-Length": str(file_size),
        "X-Upload-Content-Type": content_type,
    }
    body = {
        "snippet": {
            "title": title,
            "categoryId": cfg.category_id,
        },
        "status": {
            "privacyStatus": cfg.privacy_status,
        },
    }
    resp = session.post(
        YOUTUBE_UPLOAD_INIT_URL,
        params=params,
        headers=headers,
        data=json.dumps(body),
        timeout=30,
    )
    # YouTube returns 200 or 201 with Location header for resumable session.
    if resp.status_code not in (200, 201):
        raise RuntimeError(
            f"YouTube init failed: {resp.status_code} {resp.text[:300]}"
        )
    location = resp.headers.get("Location")
    if not location:
        raise RuntimeError(f"YouTube init missing Location header: {resp.headers}")
    return location


def _youtube_upload_resumable(
    session: requests.Session,
    upload_url: str,
    access_token: str,
    file_path: str,
    file_size: int,
    content_type: str,
) -> str:
    chunk_size = 8 * 1024 * 1024  # 8MB chunks
    start = 0

    with open(file_path, "rb") as f:
        while start < file_size:
            end = min(start + chunk_size - 1, file_size - 1)
            f.seek(start)
            data = f.read(end - start + 1)
            if not data:
                raise RuntimeError(f"Read empty chunk at bytes={start}-{end}")

            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Length": str(len(data)),
                "Content-Type": content_type,
                "Content-Range": f"bytes {start}-{end}/{file_size}",
            }
            resp = session.put(
                upload_url,
                headers=headers,
                data=data,
                timeout=60 * 10,
            )

            if resp.status_code in (200, 201):
                result = resp.json()
                vid = result.get("id")
                if not vid:
                    raise RuntimeError(f"Upload succeeded but missing id: {result}")
                return vid

            # 308 = Resume Incomplete
            if resp.status_code == 308:
                range_header = resp.headers.get("Range")
                if range_header and "-" in range_header:
                    # Example: Range: bytes=0-12345
                    last_end = int(range_header.split("-")[-1])
                    start = last_end + 1
                    continue
                # Fallback: assume this chunk was uploaded
                start = end + 1
                continue

            raise RuntimeError(
                f"YouTube upload failed: {resp.status_code} {resp.text[:300]}"
            )

    raise RuntimeError("YouTube upload ended without success")


def upload_camera_to_youtube(camera_uuid: str) -> None:
    """
    Worker: transitions camera.status UPLOADING -> SUCCESS/FAILED.

    On SUCCESS: delete local video source file.
    On FAILED: keep file for download.
    """
    cfg = _get_config()
    camera: Camera = Camera.query.filter_by(uuid=camera_uuid).first()
    if not camera:
        current_app.logger.warning("youtube_upload: camera not found uuid=%s", camera_uuid)
        return

    if camera.status != "UPLOADING":
        return

    if not cfg:
        camera.status = "FAILED"
        db.session.commit()
        current_app.logger.warning(
            "youtube_upload: missing YouTube upload config (YOUTUBE_UPLOAD_REFRESH_TOKEN/clients); camera uuid=%s",
            camera_uuid,
        )
        return

    file_path_abs = _video_file_abs_path(camera)
    if not path.exists(file_path_abs):
        camera.status = "FAILED"
        db.session.commit()
        current_app.logger.error(
            "youtube_upload: local file missing abs=%s camera uuid=%s",
            file_path_abs,
            camera_uuid,
        )
        return

    file_size = path.getsize(file_path_abs)
    # We re-encode to webm in the recording pipeline.
    content_type = "video/webm"

    title = _build_camera_title(camera)
    access_token = _get_access_token(cfg)

    session = requests.Session()
    upload_url = _youtube_init_request(
        session=session,
        access_token=access_token,
        file_size=file_size,
        content_type=content_type,
        title=title,
        cfg=cfg,
    )

    try:
        video_id = _youtube_upload_resumable(
            session=session,
            upload_url=upload_url,
            access_token=access_token,
            file_path=file_path_abs,
            file_size=file_size,
            content_type=content_type,
        )
    except Exception:
        camera.status = "FAILED"
        db.session.commit()
        current_app.logger.exception("youtube_upload: upload failed camera uuid=%s", camera_uuid)
        return

    # SUCCESS
    camera.link = video_id
    camera.status = "SUCCESS"
    db.session.commit()

    # Delete local file to save disk.
    try:
        if path.exists(file_path_abs):
            os.remove(file_path_abs)
    except OSError:
        current_app.logger.warning(
            "youtube_upload: could not delete local file camera uuid=%s path=%s",
            camera_uuid,
            file_path_abs,
        )

