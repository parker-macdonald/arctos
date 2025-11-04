"""
Main routes (homepage, etc.)
"""
from flask import Blueprint, render_template
from flask_login import current_user
from models import Tournament, TeamRegistration, PlayerRegistration, TO

bp = Blueprint('main', __name__)


@bp.route('/')
def index():
    """Homepage showing published tournaments."""
    # Get published tournaments
    published_tournaments = Tournament.query.filter_by(published=True).order_by(Tournament.start_date.desc()).all()
    
    # Get tournaments where current user is TO (if logged in)
    to_tournaments = []
    if current_user.is_authenticated:
        to_entries = TO.query.filter_by(user_id=current_user.id, user_type=current_user.__class__.__name__.lower()).all()
        tournament_urls = [entry.event for entry in to_entries]
        to_tournaments = Tournament.query.filter(Tournament.url.in_(tournament_urls)).order_by(Tournament.start_date.desc()).all()
    
    # Compute registered team counts per tournament
    team_counts = {}
    for t in published_tournaments:
        team_counts[t.url] = TeamRegistration.query.filter_by(event=t.url, status='CONFIRMED').count()

    # Compute current user's registration/payment status per tournament
    user_reg_status = {}
    if current_user.is_authenticated:
        user_type = current_user.__class__.__name__
        for t in published_tournaments:
            if user_type == 'Team':
                reg = TeamRegistration.query.filter_by(event=t.url, team=current_user.id).first()
                if reg:
                    user_reg_status[t.url] = {
                        'type': 'team',
                        'status': reg.status or '',
                        'paid': bool(reg.paid),
                        'amount_paid': reg.amount_paid or 0.0,
                    }
            elif user_type == 'Player':
                reg = PlayerRegistration.query.filter_by(event=t.url, player=current_user.id).first()
                if reg:
                    user_reg_status[t.url] = {
                        'type': 'player',
                        'status': reg.status or '',
                        'paid': bool(reg.paid),
                        'amount_paid': reg.amount_paid or 0.0,
                    }

    return render_template(
        'index.html',
        tournaments=published_tournaments,
        to_tournaments=to_tournaments,
        team_counts=team_counts,
        user_reg_status=user_reg_status,
    )


@bp.route('/teams')
def teams():
    """List all teams."""
    from flask import request
    from models import Team
    search = request.args.get('search', '')
    if search:
        teams = Team.query.filter(Team.name.contains(search) | Team.id.contains(search)).all()
    else:
        teams = Team.query.all()
    return render_template('teams.html', teams=teams)


@bp.route('/players')
def players():
    """List all players."""
    from flask import request
    from models import Player
    search = request.args.get('search', '')
    if search:
        players = Player.query.filter(Player.name.contains(search) | Player.id.contains(search)).all()
    else:
        players = Player.query.all()
    return render_template('players.html', players=players)

