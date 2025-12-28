"""
Match operations service.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Iterable, List, Optional

from app.error_values import Err, Ok, Result, allow_Q
from app.exceptions import (
    ArctosError,
    NotFoundError,
    UnauthorizedError,
    ValidationError,
)
from app.services.permission_service import PermissionService

if TYPE_CHECKING:  # pragma: no cover
    from models import Match


def _dedup(seq: Iterable[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for x in seq:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


@dataclass(frozen=True)
class MatchService:
    @staticmethod
    @allow_Q
    def start_match(
        tournament_url: str,
        match_id: str,
        user,
        *,
        team1_players_csv: str = "",
        team2_players_csv: str = "",
        match_notes: str = "",
        stones_per_set: Optional[str] = None,
    ) -> Result["Match", ArctosError]:
        from models import Match, Tournament, Field, db
        from app.utils.scheduling import recompute_all_match_times

        if not match_id:
            return Err(ValidationError("Match ID required"))

        match = Match.query.get(match_id)
        if not match or match.event != tournament_url:
            return Err(NotFoundError("Match not found"))

        if not PermissionService.can_head_ref_match(tournament_url, user, match=match):
            return Err(
                UnauthorizedError(
                    "You are not authorized to start matches for this tournament"
                )
            )

        if match.status != "NOT_STARTED":
            return Err(
                ValidationError("This match has already been started or completed")
            )

        raw_team1 = (team1_players_csv or "").strip()
        raw_team2 = (team2_players_csv or "").strip()
        team1_players = [
            pid for pid in (raw_team1.split(",") if raw_team1 else []) if pid
        ]
        team2_players = [
            pid for pid in (raw_team2.split(",") if raw_team2 else []) if pid
        ]

        overlap = set(team1_players) & set(team2_players)
        if overlap:
            return Err(ValidationError("A player cannot be selected for both teams"))

        tournament_obj = Tournament.query.get(tournament_url)
        max_roster = getattr(tournament_obj, "max_team_size_field", None)
        try:
            max_roster = int(max_roster) if max_roster is not None else None
        except Exception:
            max_roster = None
        if max_roster and (
            len(team1_players) > max_roster or len(team2_players) > max_roster
        ):
            return Err(ValidationError("Too many players selected for a team"))

        team1_players = _dedup(team1_players)
        team2_players = _dedup(team2_players)

        # Mutations start here (after validation)
        match.status = "IN_PROGRESS"
        # Use local server time (naive) for display consistency on localhost
        match.confirmed_start_time = datetime.now()

        match.initial_notes = match_notes or ""
        match.team1_players = json.dumps(team1_players)
        match.team2_players = json.dumps(team2_players)
        match.started_by = user.id
        match.started_at = datetime.utcnow()

        if match.set_type == "STONES":
            if stones_per_set:
                try:
                    spp = int(stones_per_set)
                except ValueError:
                    return Err(ValidationError("Invalid stones per set value"))
            else:
                # Use stones_per_set with fallback to deprecated nstonesperset for backward compatibility
                spp = match.stones_per_set or match.nstonesperset or 100
            match.stones_per_set = spp
            match.stones_remaining = spp

        # Get camera stream start times for all cameras on this field
        if match.field:
            field_obj = Field.query.filter_by(
                event=tournament_url, name=match.field
            ).first()
            if field_obj and field_obj.camera:
                from app.utils.camera_helpers import get_all_camera_stream_starts

                stream_starts = get_all_camera_stream_starts(field_obj)
                if stream_starts:
                    match.camera_stream_starts = json.dumps(stream_starts)

        db.session.commit()

        # Update predicted times first
        try:
            recompute_all_match_times(tournament_url)
            db.session.commit()
        except Exception:
            # Preserve existing behavior: don't fail match start if scheduling update fails
            pass

        return Ok(match)
