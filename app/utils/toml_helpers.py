"""
TOML parsing and writing utilities for schedule import/export.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import tomli

from app.error_values import Err, Ok, Result
from app.exceptions import ArctosError, ValidationError


def parse_toml_schedule(content: str) -> Result[dict[str, Any], ArctosError]:
    """
    Parse TOML schedule content with validation.

    Returns Result containing parsed data dict with keys: 'event', 'tags', 'fields', 'matches'.
    """
    try:
        data = tomli.loads(content)
    except Exception as e:
        return Err(ValidationError(f"Invalid TOML format: {str(e)}"))

    # Validate structure
    if not isinstance(data, dict):
        return Err(ValidationError("TOML root must be a table"))

    # Extract event (required)
    event = data.get("event")
    if not event or not isinstance(event, str):
        return Err(ValidationError("Missing or invalid 'event' field in TOML"))

    # Extract tags (optional, defaults to empty list)
    tags = data.get("tags", [])
    if not isinstance(tags, list):
        return Err(ValidationError("'tags' must be an array of tables"))

    # Extract fields (optional, defaults to empty list)
    fields = data.get("fields", [])
    if not isinstance(fields, list):
        return Err(ValidationError("'fields' must be an array of tables"))

    # Extract matches (optional, defaults to empty list)
    matches = data.get("matches", [])
    if not isinstance(matches, list):
        return Err(ValidationError("'matches' must be an array of tables"))

    return Ok(
        {
            "event": event,
            "tags": tags,
            "fields": fields,
            "matches": matches,
        }
    )


def write_toml_schedule(
    event: str,
    tags: list[dict[str, Any]],
    fields: list[dict[str, Any]],
    matches: list[dict[str, Any]],
    *,
    metadata: dict[str, Any] | None = None,
) -> str:
    """
    Write schedule data to TOML format.

    Args:
        event: Tournament URL
        tags: List of tag dicts with 'id', 'name', and optional 'team' (team id)
        fields: List of field dicts with 'id', 'name', 'camera'
        matches: List of match dicts with match attributes
        metadata: Optional metadata dict (e.g., export_date, version)

    Returns:
        TOML string
    """
    lines = []

    # Add metadata comment header
    if metadata:
        lines.append("# Schedule Export")
        for key, value in metadata.items():
            lines.append(f"# {key}: {value}")
        lines.append("")

    # Event
    lines.append(f'event = "{_escape_toml_string(event)}"')
    lines.append("")

    # Tags
    if tags:
        lines.append("# Tags")
        for tag in tags:
            lines.append("[[tags]]")
            if "id" in tag and tag["id"] is not None:
                lines.append(f'id = {tag["id"]}')
            if "name" in tag and tag["name"]:
                lines.append(f'name = "{_escape_toml_string(tag["name"])}"')
            if "team" in tag and tag["team"]:
                lines.append(f'team = "{_escape_toml_string(tag["team"])}"')
            lines.append("")

    # Fields
    if fields:
        lines.append("# Fields")
        for field in fields:
            lines.append("[[fields]]")
            if "id" in field and field["id"] is not None:
                lines.append(f'id = {field["id"]}')
            if "name" in field and field["name"]:
                lines.append(f'name = "{_escape_toml_string(field["name"])}"')
            if "camera" in field and field["camera"]:
                lines.append(f'camera = "{_escape_toml_string(field["camera"])}"')
            lines.append("")

    # Matches
    if matches:
        lines.append("# Matches")
        for match in matches:
            lines.append("[[matches]]")

            # UUID
            if "uuid" in match and match["uuid"]:
                lines.append(f'uuid = "{match["uuid"]}"')

            # Name (required)
            if "name" in match:
                lines.append(f'name = "{_escape_toml_string(match["name"])}"')

            # Optional string fields - only include if non-empty
            # Note: team1, team2, refs are NOT exported - they are derived from _initial fields
            for field_name in [
                "team1_initial",
                "team2_initial",
                "refs_initial",
                "field",
                "skip_condition",
            ]:
                if field_name in match and match[field_name]:
                    lines.append(
                        f'{field_name} = "{_escape_toml_string(str(match[field_name]))}"'
                    )

            # Datetime
            if "nominal_start_time" in match and match["nominal_start_time"]:
                dt = match["nominal_start_time"]
                if isinstance(dt, datetime):
                    # Format as ISO 8601 string (TOML datetime format)
                    lines.append(f'nominal_start_time = "{dt.isoformat()}"')
                else:
                    lines.append(f'nominal_start_time = "{dt}"')

            # Integer fields
            for field_name in ["nominal_length", "nsets", "stones_per_set"]:
                if field_name in match and match[field_name] is not None:
                    lines.append(f"{field_name} = {match[field_name]}")

            # String enum fields - only include if present
            for field_name in ["schedule_type", "set_type"]:
                if field_name in match and match[field_name]:
                    lines.append(f'{field_name} = "{match[field_name]}"')

            # Boolean - only include if True (False is default)
            if "ribbon" in match and match["ribbon"]:
                lines.append("ribbon = true")

            # Relationship references - only include if present
            for field_name in ["previous_match", "next_match"]:
                if field_name in match and match[field_name]:
                    lines.append(
                        f'{field_name} = "{_escape_toml_string(match[field_name])}"'
                    )

            lines.append("")

    return "\n".join(lines)


def _escape_toml_string(s: str) -> str:
    """Escape special characters in TOML strings."""
    s = str(s)
    s = s.replace("\\", "\\\\")
    s = s.replace('"', '\\"')
    s = s.replace("\n", "\\n")
    s = s.replace("\t", "\\t")
    return s
