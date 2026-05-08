"""Camera / video upload records.

Defines :class:`Camera` - one row per recorded clip, tracking the full
lifecycle from upload through S3 transfer and YouTube publication.
"""

from __future__ import annotations

import uuid

from app.models.base import db
from app.models.constants import (
    LONG_NAME_LEN,
    LONG_URL_LEN,
    SHORT_CODE_LEN,
    SHORT_LABEL_LEN,
    URL_SLUG_LEN,
    USER_ID_LEN,
    UUID_LEN,
)


class Camera(db.Model):
    """A camera recording or video upload record associated with a match.

    Tracks the full lifecycle of a video clip from initial upload through
    S3 transfer and optional YouTube publication.

    The wall-clock / video-offset synchronisation anchors live in the
    ``camera_timepoints`` join table; access them through the helpers in
    :mod:`app.services.dual_write`.

    Attributes:
        uuid: UUID primary key, auto-generated.
        match_uuid: UUID FK of the :class:`~app.models.match.Match` this
            recording belongs to.
        event: Tournament URL slug (denormalised for efficient filtering
            without joins).
        field: Field index within the tournament (0-based integer).
        name: Human-readable display name for the recording.
        source_type: Where the recording originated (e.g. ``"recording"``).
        uploaded_by_user_id: ID of the user who uploaded the recording.
        uploaded_by_user_type: ``"player"`` or ``"team"``.
        status: Upload/processing status: ``"UPLOADING"``, ``"SUCCESS"``,
            or ``"FAILED"``.
        link: YouTube URL or video ID once the upload succeeds.
        file: Local file path or S3 key, used for failed or in-progress
            uploads.
    """

    __tablename__ = "cameras"

    uuid = db.Column(db.String(UUID_LEN), primary_key=True, default=lambda: str(uuid.uuid4()))

    # Camera belongs to a single match.
    match_uuid = db.Column(db.String(UUID_LEN), db.ForeignKey("matches.uuid"), nullable=False, index=True)

    # Convenience fields to avoid joins for UI / filtering.
    event = db.Column(
        db.String(URL_SLUG_LEN),
        db.ForeignKey("tournaments.url"),
        nullable=False,
        index=True,
    )
    field = db.Column(db.Integer, nullable=False, index=True)

    # Display / identity.
    name = db.Column(db.String(LONG_NAME_LEN), nullable=False)

    # Upload source tracking.
    source_type = db.Column(db.String(SHORT_LABEL_LEN), nullable=False, default="recording")

    uploaded_by_user_id = db.Column(db.String(USER_ID_LEN), nullable=True)
    uploaded_by_user_type = db.Column(db.String(SHORT_CODE_LEN), nullable=True)  # e.g. "player" or "team"

    # Output identity.
    status = db.Column(db.String(SHORT_LABEL_LEN), nullable=False, default="UPLOADING")  # UPLOADING|SUCCESS|FAILED
    link = db.Column(db.String(LONG_URL_LEN))  # YouTube URL/id when SUCCESS

    # Local/static/S3 key for FAILED downloads (and possibly for in-progress uploads).
    file = db.Column(db.String(LONG_URL_LEN))
