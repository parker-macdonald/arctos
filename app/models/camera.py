from __future__ import annotations

import uuid

from app.models.base import db


class Camera(db.Model):
    __tablename__ = "cameras"

    uuid = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # Camera belongs to a single match.
    match_uuid = db.Column(
        db.String(36), db.ForeignKey("matches.uuid"), nullable=False, index=True
    )

    # Convenience fields to avoid joins for UI / filtering.
    event = db.Column(
        db.String(100), db.ForeignKey("tournaments.url"), nullable=False, index=True
    )
    field = db.Column(db.Integer, nullable=False, index=True)

    # Display / identity.
    name = db.Column(db.String(200), nullable=False)

    # Upload source tracking.
    source_type = db.Column(db.String(50), nullable=False, default="recording")

    uploaded_by_user_id = db.Column(db.String(50), nullable=True)
    uploaded_by_user_type = db.Column(
        db.String(10), nullable=True
    )  # e.g. "player" or "team"

    # Output identity.
    status = db.Column(
        db.String(50), nullable=False, default="UPLOADING"
    )  # UPLOADING|SUCCESS|FAILED
    link = db.Column(db.String(500))  # YouTube URL/id when SUCCESS

    # Local/static/S3 key for FAILED downloads (and possibly for in-progress uploads).
    file = db.Column(db.String(500))

    # JSON arrays stored as strings (SQLite-safe). Keep format consistent with frontend expectations.
    time_world = db.Column(
        db.Text
    )  # JSON array of world timestamps; one per session/clip boundary
    time_video = db.Column(
        db.Text
    )  # JSON array of float seconds; one per session/clip boundary
