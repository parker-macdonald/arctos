"""
Match note serialization.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from app.utils.datetime_helpers import normalize_datetime
from app.utils.player_helpers import get_player_display_name


@dataclass(frozen=True)
class MatchNoteSerializer:
    @staticmethod
    def to_dict(
        note, tournament_url: str, match: Optional[Any] = None
    ) -> Dict[str, Any]:
        player_name = None
        player_display = None
        if getattr(note, "player_id", None):
            player_name, player_display = get_player_display_name(
                note.player_id, tournament_url
            )

        created_ts = normalize_datetime(getattr(note, "created_at", None)).unwrap_or(
            None
        )

        team_id = None
        target = getattr(note, "target", None)
        if match is not None and target in ("team1", "team2"):
            if target == "team1":
                team_id = getattr(match, "team1", None)
            elif target == "team2":
                team_id = getattr(match, "team2", None)

        return {
            "uuid": getattr(note, "uuid", None),
            "text": getattr(note, "text", "") or "",
            "target": target,
            "created_by": getattr(note, "created_by", None),
            "created_at": created_ts.isoformat() if created_ts else None,
            "player_id": getattr(note, "player_id", None),
            "player_name": player_name,
            "player_display": player_display,
            "team_id": team_id,
            "penalty_type_id": getattr(note, "penalty_type_id", None),
        }
