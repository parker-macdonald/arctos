"""
Jinja2 template filters for the tournament site.
"""
import json
from flask import Blueprint
from markupsafe import Markup
from models import TeamRegistration, Tournament

try:
    import markdown as _markdown
    import bleach as _bleach
except Exception:  # Fallbacks if optional deps aren't installed yet
    _markdown = None
    _bleach = None

bp = Blueprint('filters', __name__)


@bp.app_template_filter('team_registration_for_tournament')
def team_registration_for_tournament(team_id, tournament_url):
    """Get team registration for a specific tournament."""
    if not team_id:
        return None
    return TeamRegistration.query.filter_by(team=team_id, event=tournament_url).first()


@bp.app_template_filter('team_by_pseudonym_for_tournament')
def team_by_pseudonym_for_tournament(pseudonym, tournament_url):
    """Get team registration by pseudonym for a specific tournament."""
    if not pseudonym:
        return None
    return TeamRegistration.query.filter_by(pseudonym=pseudonym, event=tournament_url).first()


@bp.app_template_filter('is_head_ref')
def is_head_ref(tournament_url, player_id):
    """Check if a player is a head ref for a tournament"""
    tournament = Tournament.query.get(tournament_url)
    if not tournament or not tournament.head_refs:
        return False
    head_refs_list = [ref.strip() for ref in tournament.head_refs.split(',')]
    return player_id in head_refs_list


@bp.app_template_filter('from_json')
def from_json(json_string):
    """Parse JSON string to Python object."""
    if not json_string:
        return {}
    try:
        return json.loads(json_string)
    except (json.JSONDecodeError, TypeError):
        return {}


@bp.app_template_filter('markdown')
def render_markdown(text):
    """Render Markdown to safe HTML.

    - Converts Markdown to HTML using python-markdown if available; otherwise returns plain text.
    - Sanitizes HTML with bleach to prevent XSS while allowing common formatting tags.
    """
    if not text:
        return ''

    # If deps missing, return escaped text to avoid unsafe HTML
    if _markdown is None or _bleach is None:
        # Markup will escape by default when returned to Jinja unless marked safe
        return text

    # Convert markdown to HTML
    html = _markdown.markdown(
        text,
        extensions=[
            'extra',            # tables, fenced code, etc.
            'sane_lists',
            'smarty',
            'admonition',       # !!! note "Title" style callouts
        ],
        output_format='html5',
    )

    # Sanitize HTML
    allowed_tags = _bleach.sanitizer.ALLOWED_TAGS.union({
        'p', 'pre', 'code', 'blockquote', 'hr', 'br', 'div',
        'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
        'ul', 'ol', 'li',
        'strong', 'em', 'del', 'span',
        'table', 'thead', 'tbody', 'tr', 'th', 'td'
    })
    allowed_attrs = {
        **_bleach.sanitizer.ALLOWED_ATTRIBUTES,
        'a': ['href', 'title', 'rel', 'target'],
        'img': ['src', 'alt', 'title'],
        'span': ['class'],
        'div': ['class'],
        'p': ['class'],
        'code': ['class'],
        'table': ['class'],
        'th': ['colspan', 'rowspan'],
        'td': ['colspan', 'rowspan'],
    }
    cleaned = _bleach.clean(
        html,
        tags=list(allowed_tags),
        attributes=allowed_attrs,
        protocols=_bleach.sanitizer.ALLOWED_PROTOCOLS.union({'data'}),
        strip=True,
    )
    # Linkify plain URLs
    cleaned = _bleach.linkify(cleaned)
    return Markup(cleaned)

