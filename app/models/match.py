from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import foreign

from app.domain.enums import (
    WinnerSide,
    MatchStatus,
    ScheduleType,
    WinnerSide,
    SetType,
    parse_enum,
    MatchNoteTarget,
)
from app.models.base import db
from app.error_values import Some


class Match(db.Model):
    __tablename__ = "matches"

    uuid = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = db.Column(db.String(200), nullable=False)
    event = db.Column(db.String(100), db.ForeignKey("tournaments.url"), nullable=False)
    team1 = db.Column(db.String(50), db.ForeignKey("teams.id"))
    team2 = db.Column(db.String(50), db.ForeignKey("teams.id"))
    team1_initial = db.Column(db.String(200))
    team2_initial = db.Column(db.String(200))
    refs = db.Column(db.Text)  # comma separated team ids
    refs_initial = db.Column(db.Text)
    field = db.Column(db.String(100))
    nominal_start_time = db.Column(db.DateTime)
    confirmed_start_time = db.Column(db.DateTime)
    completed_time = db.Column(db.DateTime)
    nominal_length = db.Column(db.Integer)  # minutes
    schedule_type = db.Column(
        db.Enum(ScheduleType), default=ScheduleType.STATIC
    )  # STATIC, SAFE, FAST, BREAK, JOIN
    set_type = db.Column(
        db.Enum(SetType), default=SetType.SETS
    )  # SETS, STONES (only for non-BREAK/JOIN matches)
    ribbon = db.Column(
        db.Boolean, default=False
    )  # True if this is a ribbon game (not counted in results)
    nsets = db.Column(db.Integer)
    nstonesperset = db.Column(
        db.Integer
    )  # DEPRECATED: Use stones_per_set instead. Kept for backward compatibility.
    status = db.Column(
        db.Enum(MatchStatus), default=MatchStatus.NOT_STARTED
    )  # NOT_STARTED, IN_PROGRESS, COMPLETED
    initial_notes = db.Column(
        db.Text
    )  # notes (initial match notes, distinct from MatchNote objects)
    team1_players = db.Column(db.Text)  # JSON array of player IDs
    team2_players = db.Column(db.Text)  # JSON array of player IDs
    started_by = db.Column(db.String(50))  # user ID who started the match
    started_at = db.Column(db.DateTime)  # when match started
    stones_per_set = db.Column(db.Integer)  # for STONES matches
    stones_remaining = db.Column(db.Integer)  # for STONES matches
    finalized_by = db.Column(db.String(50))  # user ID who finalized the match
    final_notes = db.Column(db.Text)  # final notes
    match_winner = db.Column(db.Enum(WinnerSide))  # 'TEAM1' or 'TEAM2'
    team1_signature = db.Column(db.Text)  # signature data
    team2_signature = db.Column(db.Text)  # signature data
    finalized_at = db.Column(db.DateTime)  # when match was finalized
    ready_to_start = db.Column(db.Boolean, default=False)  # flag for dynamic scheduling
    ready_to_start_at = db.Column(db.DateTime)  # when ready_to_start was set
    camera_stream_starts = db.Column(
        db.Text
    )  # JSON object mapping camera_index to stream start time (ISO format)
    previous_match = db.Column(
        db.String(36), db.ForeignKey("matches.uuid"), nullable=True
    )
    next_match = db.Column(db.String(36), db.ForeignKey("matches.uuid"), nullable=True)
    skip_condition = db.Column(
        db.Text, default="false"
    )  # DSL expression that determines if match should be skipped

    # Relationships
    previous_match_obj = db.relationship(
        "Match",
        foreign_keys=[previous_match],
        remote_side=[uuid],
        post_update=True,
        backref="previous_of",
    )
    next_match_obj = db.relationship(
        "Match",
        foreign_keys=[next_match],
        remote_side=[uuid],
        post_update=True,
        backref="next_of",
    )

    def get_skip_condition_dependencies(self) -> dict[str, set[str]]:
        """
        Analyze the skip condition to determine which matches it depends on.

        Returns:
            Dictionary with keys:
            - "direct": Set of match names that must be completed (winner/loser determined)
              for this skip condition to evaluate fully
            - "skip_condition": Set of match names whose status must be known for (is-skipped MATCH)
              to evaluate

        Example:
            If skip_condition is "(== 0 (losses [Match1::winner]))", this will return:
            {"direct": {"Match1"}, "skip_condition": set()}

            If skip_condition is "(is-skipped {Match2})", this will return:
            {"direct": set(), "skip_condition": {"Match2"}}
        """
        from app.utils.dsl_dependency_analyzer import MatchDependencyAnalyzer

        if not self.skip_condition:
            return {"direct": set(), "skip_condition": set()}

        analyzer = MatchDependencyAnalyzer(self.event)
        return analyzer.analyze(self.skip_condition)

    team1_registration = db.relationship(
        "TeamRegistration",
        primaryjoin="and_(Match.team1 == foreign(TeamRegistration.team), Match.event == TeamRegistration.event)",
        uselist=False,
        viewonly=True,
    )
    team2_registration = db.relationship(
        "TeamRegistration",
        primaryjoin="and_(Match.team2 == foreign(TeamRegistration.team), Match.event == TeamRegistration.event)",
        uselist=False,
        viewonly=True,
    )

    @property
    def winner_team_id(self) -> str | None:
        match parse_enum(WinnerSide, getattr(self, "match_winner", None)):
            case Some(WinnerSide.TEAM1):
                return self.team1
            case Some(WinnerSide.TEAM2):
                return self.team2
            case _:
                return None

    @property
    def loser_team_id(self) -> str | None:
        match parse_enum(WinnerSide, getattr(self, "match_winner", None)):
            case Some(WinnerSide.TEAM1):
                return self.team2
            case Some(WinnerSide.TEAM2):
                return self.team1
            case _:
                return None

    @property
    def is_time_finalized(self) -> bool:
        """True when start time is locked: status is TIME_FINALIZED or any later state (READY_TO_START, IN_PROGRESS, COMPLETED, SKIPPED)."""
        if self.status is None:
            return False
        return self.status != MatchStatus.NOT_STARTED

    def finalize(self) -> None:
        self.finalized_at = datetime.now(timezone.utc).replace(tzinfo=None)
        if self.schedule_type in (ScheduleType.JOIN, ScheduleType.BREAK):
            self.confirmed_start_time = self.nominal_start_time
            self.status = MatchStatus.COMPLETED
            self.completed_time = (
                self.nominal_start_time
                if self.schedule_type == ScheduleType.JOIN
                else self.nominal_start_time + timedelta(minutes=self.nominal_length)
            )


class Point(db.Model):
    __tablename__ = "points"

    uuid = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    match = db.Column(db.String(36), db.ForeignKey("matches.uuid"), nullable=False)
    winner = db.Column(db.String(10))  # TEAM1, TEAM2
    rerolled = db.Column(db.Boolean, default=False)
    stamp = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
    end_stamp = db.Column(db.DateTime)
    footage = db.Column(db.String(500))
    camera_index = db.Column(
        db.Integer
    )  # Index of camera in field's camera array (0-based)
    stream_timestamp = db.Column(db.Float)  # Timestamp in seconds from stream start
    length = db.Column(db.Interval)
    nstones = db.Column(db.Integer)
    stones_at_start = db.Column(
        db.Integer
    )  # Stones remaining when this point started (for STONES matches)
    rerollreason = db.Column(db.Text)
    set_number = db.Column(db.Integer, default=1)
    notes = db.Column(db.Text)


class MatchNote(db.Model):
    __tablename__ = "match_notes"

    uuid = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    match = db.Column(db.String(36), db.ForeignKey("matches.uuid"), nullable=False)
    text = db.Column(db.Text, nullable=False)
    target = db.Column(db.Enum(MatchNoteTarget))
    created_by = db.Column(db.String(50), db.ForeignKey("players.id"), nullable=False)
    created_at = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
    # Optional link to a specific player
    player_id = db.Column(db.String(50), db.ForeignKey("players.id"))
    # Optional link to a specific point
    point_id = db.Column(db.String(36), db.ForeignKey("points.uuid"))

    # Relationships
    match_obj = db.relationship("Match", backref="match_notes")
    creator = db.relationship("Player", foreign_keys=[created_by])
    player = db.relationship("Player", foreign_keys=[player_id])
    point_obj = db.relationship("Point", foreign_keys=[point_id], backref="point_notes")
