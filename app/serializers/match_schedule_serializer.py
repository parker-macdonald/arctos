"""
Schedule serialization for import/export (tags, fields, matches).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.error_values import Err, Ok, Result
from app.exceptions import ValidationError


@dataclass(frozen=True)
class MatchScheduleSerializer:
    """Serialize/deserialize schedule data (tags, fields, matches) to/from TOML-compatible dicts."""

    @staticmethod
    def tag_to_dict(tag) -> dict[str, Any]:
        """Convert Tag model to TOML dict, omitting empty values."""
        result = {}
        if tag.id is not None:
            result["id"] = tag.id
        if tag.name:
            result["name"] = tag.name
        return result

    @staticmethod
    def field_to_dict(field) -> dict[str, Any]:
        """Convert Field model to TOML dict, omitting empty values."""
        result = {}
        if field.id is not None:
            result["id"] = field.id
        if field.name:
            result["name"] = field.name
        if field.camera:
            result["camera"] = field.camera
        return result

    @staticmethod
    def match_to_dict(match) -> dict[str, Any]:
        """Convert Match model to TOML dict, omitting empty values."""
        result = {}

        # Always include uuid and name
        if match.uuid:
            result["uuid"] = match.uuid
        if match.name:
            result["name"] = match.name

        # Optional string fields - only include if non-empty.
        # Prefer _initial (user tokens: tag::X, Match::winner, or explicit id); fall back to
        # team1/team2/refs when set directly so export still includes team info.
        if match.team1_initial:
            result["team1_initial"] = match.team1_initial
        elif getattr(match, "team1", False):
            result["team1_initial"] = match.team1
        if match.team2_initial:
            result["team2_initial"] = match.team2_initial
        elif getattr(match, "team2", False):
            result["team2_initial"] = match.team2
        if match.refs_initial:
            result["refs_initial"] = match.refs_initial
        elif getattr(match, "refs", False):
            result["refs_initial"] = match.refs
        if match.field:
            result["field"] = match.field
        if match.skip_condition:
            result["skip_condition"] = match.skip_condition

        # Convert UUIDs to match names for relationships
        if match.previous_match:
            from models import Match as MatchModel

            prev_match = MatchModel.query.filter_by(
                uuid=match.previous_match, event=match.event
            ).first()
            if prev_match:
                result["previous_match"] = prev_match.name

        if match.next_match:
            from models import Match as MatchModel

            next_match = MatchModel.query.filter_by(
                uuid=match.next_match, event=match.event
            ).first()
            if next_match:
                result["next_match"] = next_match.name

        # Numeric fields - include if not None
        if match.nominal_length is not None:
            result["nominal_length"] = match.nominal_length
        if match.nsets is not None:
            result["nsets"] = match.nsets
        if match.stones_per_set is not None:
            result["stones_per_set"] = match.stones_per_set

        # Enum fields - include if present (they're always valid values, not "empty")
        if match.schedule_type:
            result["schedule_type"] = match.schedule_type
        if match.set_type:
            result["set_type"] = match.set_type

        # Boolean - only include if True (False is default)
        if match.ribbon:
            result["ribbon"] = True

        # Datetime - only include if present
        if match.nominal_start_time:
            result["nominal_start_time"] = match.nominal_start_time

        return result

    @staticmethod
    def tag_from_dict(
        data: dict[str, Any], tournament_url: str
    ) -> Result[dict[str, Any], ValidationError]:
        """Convert TOML dict to Tag creation data."""
        if "name" not in data:
            return Err(ValidationError("Tag missing required field: name"))

        name = str(data["name"]).strip()
        if not name:
            return Err(ValidationError("Tag name cannot be empty"))

        result = {
            "event": tournament_url,
            "name": name,
        }

        # Include id if present (for same-tournament updates)
        if "id" in data:
            try:
                result["id"] = int(data["id"])
            except (ValueError, TypeError):
                return Err(ValidationError(f"Invalid tag id: {data['id']}"))

        return Ok(result)

    @staticmethod
    def field_from_dict(
        data: dict[str, Any], tournament_url: str
    ) -> Result[dict[str, Any], ValidationError]:
        """Convert TOML dict to Field creation data."""
        if "name" not in data:
            return Err(ValidationError("Field missing required field: name"))

        name = str(data["name"]).strip()
        if not name:
            return Err(ValidationError("Field name cannot be empty"))

        result = {
            "event": tournament_url,
            "name": name,
            "camera": str(data.get("camera", "")).strip() or None,
        }

        # Include id if present (for same-tournament updates)
        if "id" in data:
            try:
                result["id"] = int(data["id"])
            except (ValueError, TypeError):
                return Err(ValidationError(f"Invalid field id: {data['id']}"))

        return Ok(result)

    @staticmethod
    def match_from_dict(
        data: dict[str, Any],
        tournament_url: str,
        *,
        match_name_to_uuid: dict[str, str] | None = None,
        match_name_field_to_uuid: dict[tuple[str, str], str] | None = None,
    ) -> Result[dict[str, Any], ValidationError]:
        """
        Convert TOML dict to Match creation data.

        Args:
            data: TOML match dict
            tournament_url: Target tournament URL
            match_name_to_uuid: Optional mapping from match names to UUIDs (for resolving previous_match/next_match)
            match_name_field_to_uuid: Optional mapping from (name, field) tuples to UUIDs (for field-based resolution when duplicates exist)

        Returns:
            Result containing dict with match creation data
        """
        if "name" not in data:
            return Err(ValidationError("Match missing required field: name"))

        name = str(data["name"]).strip()
        if not name:
            return Err(ValidationError("Match name cannot be empty"))

        # Helper to check if a value is an explicit team ID (not a tag or match reference)
        def is_explicit_team_id(val: str) -> bool:
            if not val or not val.strip():
                return False
            val = val.strip()
            # Not a tag reference
            if val.lower().startswith("tag::"):
                return False
            # Not a match reference (contains ::winner or ::loser)
            if "::winner" in val.lower() or "::loser" in val.lower():
                return False
            # Must be an explicit team ID
            return True

        # Get _initial field values
        team1_initial = str(data.get("team1_initial", "")).strip() or None
        team2_initial = str(data.get("team2_initial", "")).strip() or None
        refs_initial = str(data.get("refs_initial", "")).strip() or None

        # Clear team1/team2/refs (they are derived from _initial fields)
        # But populate explicit team IDs and resolved tag references from _initial fields
        from app.utils.helpers import resolve_tag_to_team

        team1 = None
        if team1_initial:
            if is_explicit_team_id(team1_initial):
                team1 = team1_initial
            else:
                # Try to resolve as tag reference
                resolved_team = resolve_tag_to_team(team1_initial, tournament_url)
                if resolved_team:
                    team1 = resolved_team

        team2 = None
        if team2_initial:
            if is_explicit_team_id(team2_initial):
                team2 = team2_initial
            else:
                # Try to resolve as tag reference
                resolved_team = resolve_tag_to_team(team2_initial, tournament_url)
                if resolved_team:
                    team2 = resolved_team

        # For refs, populate explicit team IDs and resolved tag references maintaining index structure
        refs = None
        if refs_initial:
            refs_initial_list = [r.strip() for r in refs_initial.split(",")]
            refs_list = [""] * len(refs_initial_list)
            has_explicit_ids = False
            for i, initial_ref in enumerate(refs_initial_list):
                if initial_ref:
                    if is_explicit_team_id(initial_ref):
                        refs_list[i] = initial_ref
                        has_explicit_ids = True
                    else:
                        # Try to resolve as tag reference
                        resolved_team = resolve_tag_to_team(initial_ref, tournament_url)
                        if resolved_team:
                            refs_list[i] = resolved_team
                            has_explicit_ids = True
            if has_explicit_ids:
                refs = ", ".join(refs_list)

        schedule_type = str(data.get("schedule_type", "STATIC")).strip() or "STATIC"
        skip_condition_raw = str(data.get("skip_condition", "")).strip() or None
        # Only accept skip_condition for SAFE and FAST; ignore for other types
        skip_condition = (
            skip_condition_raw if schedule_type in ("SAFE", "FAST") else None
        )

        result = {
            "event": tournament_url,
            "name": name,
            "team1": team1,
            "team2": team2,
            "team1_initial": team1_initial,
            "team2_initial": team2_initial,
            "refs": refs,
            "refs_initial": refs_initial,
            "field": str(data.get("field", "")).strip() or None,
            "nominal_length": data.get("nominal_length"),
            "schedule_type": schedule_type,
            "set_type": str(data.get("set_type", "SETS")).strip() or "SETS",
            "ribbon": bool(data.get("ribbon", False)),
            "nsets": data.get("nsets"),
            "stones_per_set": data.get("stones_per_set"),
            "skip_condition": skip_condition,
            "previous_match": None,
            "next_match": None,
        }

        # Handle datetime
        if "nominal_start_time" in data and data["nominal_start_time"]:
            dt_value = data["nominal_start_time"]
            if isinstance(dt_value, datetime):
                result["nominal_start_time"] = dt_value
            elif isinstance(dt_value, str):
                try:
                    # Try parsing ISO format
                    result["nominal_start_time"] = datetime.fromisoformat(
                        dt_value.replace("Z", "+00:00")
                    )
                except ValueError:
                    return Err(ValidationError(f"Invalid datetime format: {dt_value}"))
            else:
                return Err(
                    ValidationError(
                        f"Invalid nominal_start_time type: {type(dt_value)}"
                    )
                )

        # Helper function to resolve match name to UUID
        def resolve_match_name(
            match_name: str, current_field: str | None
        ) -> str | None:
            """Resolve a match name to UUID, using field-based resolution if duplicates exist."""
            if not match_name:
                return None

            # First try field-based resolution if mapping provided
            if match_name_field_to_uuid and current_field:
                key = (match_name, current_field)
                if key in match_name_field_to_uuid:
                    return match_name_field_to_uuid[key]

            # Fall back to name-only mapping
            if match_name_to_uuid:
                return match_name_to_uuid.get(match_name)

            return None

        # Resolve relationship references using match name mapping
        # previous_match and next_match are now match names, not UUIDs
        # When duplicates exist, resolve to match on same field
        current_field = result["field"]
        if match_name_to_uuid or match_name_field_to_uuid:
            if "previous_match" in data and data["previous_match"]:
                prev_match_name = str(data["previous_match"]).strip()
                if prev_match_name:
                    result["previous_match"] = resolve_match_name(
                        prev_match_name, current_field
                    )

            if "next_match" in data and data["next_match"]:
                next_match_name = str(data["next_match"]).strip()
                if next_match_name:
                    result["next_match"] = resolve_match_name(
                        next_match_name, current_field
                    )
        else:
            # No mapping provided - try to resolve by name from database
            # This handles same-tournament imports where matches already exist
            # If duplicates exist, prefer match on same field
            from models import Match as MatchModel

            if "previous_match" in data and data["previous_match"]:
                prev_match_name = str(data["previous_match"]).strip()
                if prev_match_name:
                    # Try to find by name and field first (for duplicates)
                    if current_field:
                        prev_match = MatchModel.query.filter_by(
                            event=tournament_url,
                            name=prev_match_name,
                            field=current_field,
                        ).first()
                    else:
                        prev_match = None

                    # Fall back to name-only if not found
                    if not prev_match:
                        prev_match = MatchModel.query.filter_by(
                            event=tournament_url, name=prev_match_name
                        ).first()

                    if prev_match:
                        result["previous_match"] = prev_match.uuid

            if "next_match" in data and data["next_match"]:
                next_match_name = str(data["next_match"]).strip()
                if next_match_name:
                    # Try to find by name and field first (for duplicates)
                    if current_field:
                        next_match = MatchModel.query.filter_by(
                            event=tournament_url,
                            name=next_match_name,
                            field=current_field,
                        ).first()
                    else:
                        next_match = None

                    # Fall back to name-only if not found
                    if not next_match:
                        next_match = MatchModel.query.filter_by(
                            event=tournament_url, name=next_match_name
                        ).first()

                    if next_match:
                        result["next_match"] = next_match.uuid

        # Include uuid if present (for same-tournament updates)
        if "uuid" in data and data["uuid"]:
            result["uuid"] = str(data["uuid"]).strip()

        return Ok(result)
