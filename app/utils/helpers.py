"""
General helper functions for the tournament site.
"""

import hmac
import hashlib
import re
from flask import current_app
from flask_login import current_user
from models import Tournament, PlayerRegistration, Match


def can_head_ref_match(tournament_url: str, player_id: str, match=None) -> bool:
    """
    Check if a player can head ref matches for a tournament.

    Args:
        tournament_url: The tournament URL
        player_id: The player ID to check
        match: Optional Match object for match-specific checks (reffing teams)

    Returns:
        True if the player can head ref, False otherwise
    """
    tournament = Tournament.query.get(tournament_url)
    if not tournament:
        return False

    # If allow anyone is enabled, check if player is registered
    if tournament.head_refs_allow_anyone:
        player_reg = PlayerRegistration.query.filter_by(
            event=tournament_url,
            player=player_id,
            status="CONFIRMED",
        ).first()
        return player_reg is not None

    # Check explicit allowed list
    if tournament.head_refs_allowed_list:
        allowed_list = [
            ref.strip()
            for ref in tournament.head_refs_allowed_list.split(",")
            if ref.strip()
        ]
        if player_id in allowed_list:
            return True

    # Check reffing teams (requires match context)
    if tournament.head_refs_allow_reffing_teams and match:
        if match.refs:
            ref_teams = [team.strip() for team in match.refs.split(",") if team.strip()]
            # Check if player is registered on any of the ref teams
            for team_id in ref_teams:
                player_reg = PlayerRegistration.query.filter_by(
                    event=tournament_url,
                    player=player_id,
                    team=team_id,
                    status="CONFIRMED",
                ).first()
                if player_reg:
                    return True

    return False


def is_head_ref_any(viewed_player_id: str) -> bool:
    """Check if the current user is a head ref in any tournament."""
    if not current_user.is_authenticated:
        return False
    try:
        tournaments = Tournament.query.all()
        for t in tournaments:
            if can_head_ref_match(t.url, current_user.id):
                return True
    except Exception:
        return False
    return False


def resolve_team_name_to_id(team_name, tournament_url):
    """Resolve a team name/pseudonym to a team ID for a tournament."""
    from models import TeamRegistration

    # Try exact match on team ID
    from models import Team

    team = Team.query.filter_by(id=team_name).first()
    if team:
        return team.id

    # Try pseudonym in tournament
    reg = TeamRegistration.query.filter_by(
        event=tournament_url, pseudonym=team_name
    ).first()
    if reg:
        return reg.team

    return None


def check_tournament_access(tournament_url):
    """Check if current user has access to view a tournament."""
    from models import Tournament, TO

    tournament = Tournament.query.get(tournament_url)
    if not tournament:
        return False, None

    # If published, anyone can access
    if tournament.published:
        return True, tournament

    # If not published, only TOs can access
    if not current_user.is_authenticated:
        return False, tournament

    is_to = TO.query.filter_by(
        user_id=current_user.id,
        user_type=current_user.__class__.__name__.lower(),
        event=tournament_url,
    ).first()

    if not is_to:
        return False, tournament

    return True, tournament


def generate_permission_key(url_slug: str, secret_key=None):
    """
    Generate a permission key for a specific URL slug.

    Args:
        url_slug: The tournament URL slug
        secret_key: Optional secret key (defaults to app SECRET_KEY)

    Returns:
        A short hex string (first 16 characters of HMAC-SHA256)
    """
    if secret_key is None:
        secret_key = current_app.config.get("SECRET_KEY", "default-secret-key")

    # only use first 16 chars bc otherwise its annoying
    # if you need to type it out without copy-pasting
    return hmac.new(
        secret_key.encode("utf-8"),
        url_slug.lower().strip().encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:16]


def validate_permission_key(url_slug, provided_key, secret_key=None):
    """
    Validate a permission key for a specific URL slug.

    Args:
        url_slug: The tournament URL slug
        provided_key: The permission key provided by the user
        secret_key: Optional secret key (defaults to app SECRET_KEY)

    Returns:
        True if the key is valid, False otherwise
    """
    if not provided_key or not url_slug:
        return False

    # Normalize the provided key (strip whitespace, lowercase)
    provided_key = provided_key.strip().lower()

    # Generate expected key
    expected_key = generate_permission_key(url_slug, secret_key)

    # Use constant-time comparison to prevent timing attacks
    return hmac.compare_digest(provided_key, expected_key.lower())


def is_valid_url_username(username):
    """
    Validate that a username is URL-safe.

    Rules:
    - Only alphanumeric characters, hyphens, and underscores
    - Must be at least 1 character long
    - Cannot start or end with hyphen or underscore
    - Cannot contain spaces or special characters

    Args:
        username: The username to validate

    Returns:
        True if valid, False otherwise
    """
    if not username or len(username) == 0:
        return False

    # Check length (reasonable limit)
    if len(username) > 50:
        return False

    # Must start and end with alphanumeric
    if not (username[0].isalnum() and username[-1].isalnum()):
        return False

    # Only allow alphanumeric, hyphens, and underscores
    pattern = r"^[a-zA-Z0-9_-]+$"
    if not re.match(pattern, username):
        return False

    return True
