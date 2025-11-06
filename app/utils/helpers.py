"""
General helper functions for the tournament site.
"""
import hmac
import hashlib
import re
from flask import current_app
from flask_login import current_user
from models import Tournament


def is_head_ref_any(viewed_player_id: str) -> bool:
    """Check if the current user is a head ref in any tournament."""
    if not current_user.is_authenticated:
        return False
    try:
        tournaments = Tournament.query.all()
        for t in tournaments:
            if t.head_refs:
                head_refs_list = [ref.strip() for ref in t.head_refs.split(',') if ref.strip()]
                if current_user.id in head_refs_list:
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
    reg = TeamRegistration.query.filter_by(event=tournament_url, pseudonym=team_name).first()
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
        event=tournament_url
    ).first()
    
    if not is_to:
        return False, tournament
    
    return True, tournament


def generate_permission_key(url_slug, secret_key=None):
    """
    Generate a permission key for a specific URL slug.
    
    Args:
        url_slug: The tournament URL slug
        secret_key: Optional secret key (defaults to app SECRET_KEY)
    
    Returns:
        A short hex string (first 16 characters of HMAC-SHA256)
    """
    if secret_key is None:
        secret_key = current_app.config.get('SECRET_KEY', 'default-secret-key')
    
    # Normalize the URL slug (lowercase, strip whitespace)
    normalized_slug = url_slug.lower().strip()
    
    # Generate HMAC-SHA256 hash
    hmac_obj = hmac.new(
        secret_key.encode('utf-8'),
        normalized_slug.encode('utf-8'),
        hashlib.sha256
    )
    
    # Return first 16 characters of hex digest for easier sharing
    return hmac_obj.hexdigest()[:16]


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
    pattern = r'^[a-zA-Z0-9_-]+$'
    if not re.match(pattern, username):
        return False
    
    return True

