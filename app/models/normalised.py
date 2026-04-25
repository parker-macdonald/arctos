"""Normalised join tables that replace previously-encoded list/blob columns.

These models normalise columns that historically stored multiple values in
a single cell (comma-separated strings or JSON arrays). Each model has a
unique constraint that enforces invariants the application code previously
had to maintain in Python, plus real foreign keys so deletes cascade
correctly and orphan rows cannot exist.

The legacy blob columns they replace are still present on the original
tables and remain authoritative until application code switches over. Until
that happens the new tables are populated by a backfill script and kept in
sync by dual-write code (none of which exists yet — that is later work).
The schema definitions here are intentionally additive; nothing on the
existing schema is modified.

"""

from __future__ import annotations

from app.domain.enums import WinnerSide
from app.models.base import db
from app.models.constants import (
    LONG_NAME_LEN,
    URL_SLUG_LEN,
    USER_ID_LEN,
    UUID_LEN,
)


class HeadRefAllowList(db.Model):  # type: ignore[misc]
    """Players explicitly permitted to head-ref a specific tournament.

    Normalises ``Tournament.head_refs_allowed_list`` (formerly a
    comma-separated text column) into a proper join table with foreign-key
    enforcement. A row's presence means the player is on the allow-list for
    that event; absence means they are not permitted (subject to the
    ``head_refs_allow_anyone`` and ``head_refs_allow_reffing_teams``
    overrides on the parent ``Tournament``).

    Attributes:
        id: Auto-increment primary key.
        event: Tournament URL slug the allow-list entry applies to.
        player_id: ID of the permitted player.
    """

    __tablename__ = "headref_allowlist"

    id = db.Column(db.Integer, primary_key=True)
    event = db.Column(
        db.String(URL_SLUG_LEN),
        db.ForeignKey("tournaments.url"),
        nullable=False,
    )
    player_id = db.Column(
        db.String(USER_ID_LEN),
        db.ForeignKey("players.id"),
        nullable=False,
    )

    __table_args__ = (db.UniqueConstraint("event", "player_id", name="uq_headref_allowlist_event_player"),)


class MatchReferee(db.Model):  # type: ignore[misc]
    """One referee slot for a match, in slot order.

    Normalises ``Match.refs`` and ``Match.refs_initial`` (formerly parallel
    comma-separated text columns) into a join table. ``slot`` is the
    0-based position in the original comma-separated list and preserves
    ordering. ``team_id`` is ``NULL`` until the ASS expression in
    ``initial`` resolves to a concrete team via the dependency resolver.

    Attributes:
        id: Auto-increment primary key.
        match_uuid: UUID of the parent match.
        slot: 0-based slot index. Position in the original ref list.
        team_id: Resolved team ID, or ``NULL`` while ``initial`` is still
            a placeholder expression.
        initial: Original ASS expression (e.g. ``"Match A::winner"``) or
            an explicit team ID, preserved verbatim for re-resolution.
    """

    __tablename__ = "match_referees"

    id = db.Column(db.Integer, primary_key=True)
    match_uuid = db.Column(
        db.String(UUID_LEN),
        db.ForeignKey("matches.uuid"),
        nullable=False,
    )
    slot = db.Column(db.Integer, nullable=False)
    team_id = db.Column(
        db.String(USER_ID_LEN),
        db.ForeignKey("teams.id"),
        nullable=True,
    )
    initial = db.Column(db.String(LONG_NAME_LEN))

    __table_args__ = (db.UniqueConstraint("match_uuid", "slot", name="uq_match_referees_match_slot"),)


class MatchPlayer(db.Model):  # type: ignore[misc]
    """A player on a specific side of a match field roster.

    Normalises ``Match.team1_players`` and ``Match.team2_players``
    (formerly JSON arrays) into a join table. The unique constraint on
    ``(match_uuid, player_id)`` enforces that a player cannot appear on
    both sides of the same match simultaneously — that would be a data
    error.

    Attributes:
        id: Auto-increment primary key.
        match_uuid: UUID of the parent match.
        player_id: ID of the participating player.
        side: Which side the player is on (``TEAM1`` or ``TEAM2``).
    """

    __tablename__ = "match_players"

    id = db.Column(db.Integer, primary_key=True)
    match_uuid = db.Column(
        db.String(UUID_LEN),
        db.ForeignKey("matches.uuid"),
        nullable=False,
    )
    player_id = db.Column(
        db.String(USER_ID_LEN),
        db.ForeignKey("players.id"),
        nullable=False,
    )
    side = db.Column(db.Enum(WinnerSide), nullable=False)

    __table_args__ = (db.UniqueConstraint("match_uuid", "player_id", name="uq_match_players_match_player"),)


class CameraTimepoint(db.Model):  # type: ignore[misc]
    """A single synchronisation anchor point for a camera recording.

    Normalises ``Camera.time_world`` and ``Camera.time_video`` (formerly
    two parallel JSON arrays of equal length) into a join table. Each row
    pairs one wall-clock timestamp with the corresponding offset in the
    video file, allowing the footage pipeline to interpolate exact video
    positions for any real-world timestamp. ``sequence`` is the 0-based
    position in the original arrays and must be preserved for
    interpolation order.

    Attributes:
        id: Auto-increment primary key.
        camera_uuid: UUID of the parent camera recording.
        sequence: 0-based position in the original timepoint arrays.
            Preserved so interpolation order is unambiguous.
        time_world: ISO 8601 wall-clock timestamp string.
        time_video: Seconds offset into the video file.
    """

    __tablename__ = "camera_timepoints"

    id = db.Column(db.Integer, primary_key=True)
    camera_uuid = db.Column(
        db.String(UUID_LEN),
        db.ForeignKey("cameras.uuid"),
        nullable=False,
    )
    sequence = db.Column(db.Integer, nullable=False)
    time_world = db.Column(db.String(50))
    time_video = db.Column(db.Float)

    __table_args__ = (db.UniqueConstraint("camera_uuid", "sequence", name="uq_camera_timepoints_camera_sequence"),)
