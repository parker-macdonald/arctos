"""
General helper functions for the tournament site.
"""
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

