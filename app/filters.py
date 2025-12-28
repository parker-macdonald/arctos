"""
Jinja2 template filters for the tournament site.
"""

import json
import hmac
import hashlib
import base64
from datetime import timezone, timedelta
from flask import Blueprint, current_app, url_for
from markupsafe import Markup
from models import TeamRegistration, Tournament
from app.utils.helpers import can_head_ref_match
import markdown
import bleach

bp = Blueprint("filters", __name__)


@bp.app_template_filter("team_registration_for_tournament")
def team_registration_for_tournament(team_id, tournament_url):
    """Get team registration for a specific tournament."""
    if not team_id:
        return None
    return TeamRegistration.query.filter_by(team=team_id, event=tournament_url).first()


@bp.app_template_filter("team_by_pseudonym_for_tournament")
def team_by_pseudonym_for_tournament(pseudonym, tournament_url):
    """Get team registration by pseudonym for a specific tournament."""
    if not pseudonym:
        return None
    return TeamRegistration.query.filter_by(
        pseudonym=pseudonym, event=tournament_url
    ).first()


@bp.app_template_filter("is_head_ref")
def is_head_ref(tournament_url, player_id):
    """Check if a player is a head ref for a tournament (without match context)"""
    return can_head_ref_match(tournament_url, player_id, match=None)


@bp.app_template_filter("can_head_ref_match")
def can_head_ref_match_filter(tournament_url, player_id, match=None):
    """Check if a player can head ref a specific match"""
    return can_head_ref_match(tournament_url, player_id, match=match)


@bp.app_template_filter("from_json")
def from_json(json_string):
    """Parse JSON string to Python object."""
    if not json_string:
        return {}
    try:
        return json.loads(json_string)
    except (json.JSONDecodeError, TypeError):
        return {}


@bp.app_template_filter("markdown")
def render_markdown(text):
    """Render Markdown to safe HTML.

    - Converts Markdown to HTML using python-markdown if available; otherwise returns plain text.
    - Sanitizes HTML with bleach to prevent XSS while allowing common formatting tags.
    """
    if not text:
        return ""

    # Convert markdown to HTML
    html = markdown.markdown(
        text,
        extensions=[
            "extra",  # tables, fenced code, etc.
            "sane_lists",
            "smarty",
            "admonition",  # !!! note "Title" style callouts
        ],
        output_format="html5",
    )

    return Markup(bleach.linkify(html))


@bp.app_template_filter("localtime")
def localtime(dt, format_str="%Y-%m-%d %H:%M"):
    """Convert UTC datetime to local time for display.

    Since the server doesn't know the user's timezone, this outputs
    the datetime in a format that JavaScript can convert on the client side.
    Returns a span with data-utc attribute for JS conversion.
    """
    if not dt:
        return ""

    # If datetime is naive (no timezone), assume it's UTC
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    # Output ISO format for JavaScript to parse
    iso_str = dt.isoformat()
    # Also provide a server-side formatted version as fallback
    formatted = dt.strftime(format_str)

    # Store the format string in a data attribute so JS knows how to format
    return Markup(
        f'<span class="utc-timestamp" data-utc="{iso_str}" data-format="{format_str}">{formatted}</span>'
    )


@bp.app_template_filter("utc_iso")
def utc_iso(dt):
    """Convert datetime to UTC ISO format with 'Z' suffix for JavaScript.

    Ensures the datetime is timezone-aware (UTC) and returns ISO format
    with 'Z' suffix so JavaScript interprets it as UTC.
    """
    if not dt:
        return ""

    # If datetime is naive (no timezone), assume it's UTC
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    # Return ISO format with 'Z' suffix for UTC
    return dt.isoformat().replace("+00:00", "Z")


@bp.app_template_filter("add_minutes")
def add_minutes(dt, minutes):
    """Add minutes to a datetime."""
    if not dt or not minutes:
        return dt
    # Store original timezone state
    was_naive = dt.tzinfo is None
    # Ensure naive datetimes are treated as UTC for consistency
    if was_naive:
        dt = dt.replace(tzinfo=timezone.utc)
    result = dt + timedelta(minutes=int(minutes))
    # Return naive datetime if original was naive (for compatibility)
    if was_naive:
        return result.replace(tzinfo=None)
    return result


@bp.app_template_filter("to_utc")
def to_utc(dt):
    """Normalize datetime to UTC (timezone-aware)."""
    if not dt:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    # If already timezone-aware, convert to UTC
    return dt.astimezone(timezone.utc)


@bp.app_template_filter("camera_url")
def camera_url(tournament_url, field_name):
    """Generate camera recording URL with access key for a field."""
    if not tournament_url or not field_name:
        return ""

    try:
        from app.utils.camera_helpers import generate_camera_key

        access_key = generate_camera_key(tournament_url, field_name)

        # Generate the full URL
        base_url = url_for(
            "tournaments.camera_page",
            tournament_url=tournament_url,
            field=field_name,
            key=access_key,
            _external=True,
        )
        return base_url
    except Exception:
        # Fallback if there's an error
        return f"/{tournament_url}/camera?field={field_name}&key="


@bp.app_template_filter("merge_refs")
def merge_refs(match):
    """
    Merge refs and refs_initial at the item level.

    For each position, use the value from refs if it's non-empty,
    otherwise use the value from refs_initial.

    Returns a comma-separated string of merged refs.
    """
    if not match:
        return ""

    refs_str = match.refs or ""
    refs_initial_str = match.refs_initial or ""

    # If refs_initial is empty, just return refs
    if not refs_initial_str:
        return refs_str

    # Split both lists
    refs_list = [r.strip() for r in refs_str.split(",")] if refs_str else []
    refs_initial_list = (
        [r.strip() for r in refs_initial_str.split(",")] if refs_initial_str else []
    )

    # Use refs_initial as the base (it defines the structure)
    merged = []
    for i, initial_ref in enumerate(refs_initial_list):
        # If refs has a value at this position, use it; otherwise use refs_initial
        if i < len(refs_list) and refs_list[i]:
            merged.append(refs_list[i])
        elif initial_ref:
            merged.append(initial_ref)
        # Skip empty positions

    return ", ".join(merged)
