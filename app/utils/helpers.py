"""
General helper functions for the tournament site.
"""

import hmac
import hashlib
import re
from flask import current_app
from flask_login import current_user
from app.domain.enums import RegistrationStatus
from models import Tournament, PlayerRegistration, TeamRegistration, Team


def get_registrable_config(tournament):
    """Return the effective :class:`~app.models.registrable_config.RegistrableConfig` for a tournament.

    League tournaments inherit the league's config; standalone tournaments
    have their own config.

    Args:
        tournament: A :class:`~app.models.tournament.Tournament` instance.

    Returns:
        The :class:`~app.models.registrable_config.RegistrableConfig` object,
        or ``None`` if neither the league nor the tournament has one.
    """
    if getattr(tournament, "league_id", None):
        from models import League

        league = League.query.get(tournament.league_id)
        return league.registrable_config if league else None
    return getattr(tournament, "registrable_config", None)


def get_penalty_types_for_tournament(tournament):
    """
    Get penalty types for a tournament.

    When tournament.league_id is set, returns the league's penalty types.
    When league_id is null (standalone tournament), returns the tournament's penalty types.
    """
    from models import PenaltyType

    if getattr(tournament, "league_id", None):
        return PenaltyType.query.filter_by(league_id=tournament.league_id).all()
    return PenaltyType.query.filter_by(event=tournament.url).all()


def match_event_urls_for_penalties(tournament):
    """
    Return list of event URLs to use when querying Match for penalties/notes.

    For league events, returns all event URLs in the league so penalty counts and
    penalty lists include matches from every event in the league. For standalone
    tournaments, returns just this event's URL.
    """
    if getattr(tournament, "league_id", None):
        return [t.url for t in Tournament.query.filter_by(league_id=tournament.league_id).all()]
    return [tournament.url]


DEFAULT_PENALTY_COLORS = [
    "FF0000",  # Red
    "FF8C00",  # Dark Orange
    "FFD700",  # Gold
    "32CD32",  # Lime Green
    "008000",  # Green
    "00CED1",  # Dark Turquoise
    "1E90FF",  # Dodger Blue
    "0000FF",  # Blue
    "8A2BE2",  # Blue Violet
    "FF00FF",  # Magenta
    "C71585",  # Medium Violet Red
    "A52A2A",  # Brown
    "808080",  # Gray
    "000000",  # Black
]


def get_next_penalty_color(existing_colors: set[str]) -> str:
    """Return the first default penalty colour not already in use.

    Iterates :data:`DEFAULT_PENALTY_COLORS` in order and returns the first
    colour absent from *existing_colors*.

    Args:
        existing_colors: Set of 6-character hex colour strings already
            assigned to existing penalty types.

    Returns:
        A 6-character hex colour string (no ``#``).  Falls back to
        ``"000000"`` when all defaults are taken.
    """
    for color in DEFAULT_PENALTY_COLORS:
        if color not in existing_colors:
            return color
    return "000000"  # Default fallback


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

    # Check explicit allowed list
    if tournament.head_refs_allowed_list:
        allowed_list = [ref.strip() for ref in tournament.head_refs_allowed_list.split(",") if ref.strip()]
        if player_id in allowed_list:
            return True

    # If allow anyone is enabled, check if player is registered
    if tournament.head_refs_allow_anyone:
        player_reg = PlayerRegistration.query.filter_by(
            event=tournament_url,
            player=player_id,
            status=RegistrationStatus.CONFIRMED,
        ).first()
        return player_reg is not None

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
                    status=RegistrationStatus.CONFIRMED,
                ).first()
                if player_reg:
                    return True

    return False


def resolve_team_name_to_id(team_name, tournament_url):
    """Resolve a team name/pseudonym to (team_id, initial_display) for a tournament.
    Only resolves to a team ID when that team has a CONFIRMED registration for the event.
    Match refs (MatchName::winner/loser) and tag refs (tag::Name) are not resolved here and
    are stored as initial display text. Returns (id, None) when found; (None, team_name) otherwise.
    """
    from models import TeamRegistration, Team

    # Try exact match on team ID - only accept if team is registered (CONFIRMED) for this event
    team = Team.query.filter_by(id=team_name).first()
    if team:
        reg = TeamRegistration.query.filter_by(
            event=tournament_url, team=team.id, status=RegistrationStatus.CONFIRMED
        ).first()
        if reg:
            return (team.id, None)
        return (None, team_name)

    # Try pseudonym in tournament - only CONFIRMED registrations
    reg = TeamRegistration.query.filter_by(
        event=tournament_url,
        pseudonym=team_name,
        status=RegistrationStatus.CONFIRMED,
    ).first()
    if reg:
        return (reg.team, None)

    return (None, team_name)


def get_team_display_name_for_event(tournament_url: str, team_id: str) -> str:
    """Return the best display name for a team within a specific tournament.

    Priority:

    1. :class:`~app.models.registration.TeamRegistration` pseudonym (if
       confirmed and non-empty).
    2. :attr:`~app.models.user.Team.name`.
    3. *team_id* as a fallback.

    Args:
        tournament_url: Tournament URL slug used to look up the registration.
        team_id: The team's unique identifier.

    Returns:
        A non-empty display string.
    """
    if not team_id:
        return ""
    from app.domain.enums import TeamRegistrationStatus

    reg = TeamRegistration.query.filter_by(
        event=tournament_url, team=team_id, status=TeamRegistrationStatus.CONFIRMED
    ).first()
    if reg and getattr(reg, "pseudonym", None):
        return reg.pseudonym
    team = Team.query.get(team_id)
    if team and getattr(team, "name", None):
        return team.name
    return team_id


def resolve_tag_to_team(tag_ref: str, tournament_url: str) -> str | None:
    """Resolve a tag reference (tag::TAG_NAME) to a team ID by querying the Tag table.

    Args:
        tag_ref: Tag reference string (e.g., "tag::Pool A")
        tournament_url: Tournament URL

    Returns:
        Team ID if tag exists and has a team assigned, None otherwise
    """
    from models import Tag

    if not tag_ref or not tag_ref.strip().lower().startswith("tag::"):
        return None

    tag_name = tag_ref[5:].strip()  # Remove "tag::" prefix
    if not tag_name:
        return None

    tag = Tag.query.filter_by(event=tournament_url, name=tag_name).first()
    if tag and tag.team:
        return tag.team
    return None


def check_tournament_access(tournament_url: str):
    """Check whether the current Flask user may view a tournament.

    A tournament is accessible when it is published, or when the current
    user is a Tournament Organiser for the event or its league.

    Args:
        tournament_url: The URL slug of the tournament to check.

    Returns:
        A ``(has_access, tournament)`` tuple.  *has_access* is ``True`` when
        access is granted; *tournament* is the
        :class:`~app.models.tournament.Tournament` instance (or ``None`` when
        the tournament does not exist).
    """
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

    is_to = None
    if tournament.league_id:
        is_to = TO.query.filter_by(
            user_id=current_user.id,
            user_type=current_user.__class__.__name__.lower(),
            league_id=tournament.league_id,
        ).first()
    if not is_to:
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
