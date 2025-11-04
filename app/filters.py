"""
Jinja2 template filters for the tournament site.
"""
import json
from flask import Blueprint
from models import TeamRegistration, Tournament

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

