"""
Main routes (homepage, etc.)
"""
from flask import Blueprint, render_template, url_for, Response
from flask_login import current_user
from models import Tournament, TeamRegistration, PlayerRegistration, TO
from datetime import datetime

bp = Blueprint('main', __name__)


@bp.route('/')
def index():
    """Homepage showing published tournaments."""
    # Get published tournaments
    published_tournaments = Tournament.query.filter_by(published=True).all()
    
    # Get tournaments where current user is TO (if logged in) - including unpublished ones
    to_tournament_urls = []
    if current_user.is_authenticated:
        to_entries = TO.query.filter_by(user_id=current_user.id, user_type=current_user.__class__.__name__.lower()).all()
        to_tournament_urls = [entry.event for entry in to_entries]
    
    # Combine published tournaments with TO tournaments (avoiding duplicates)
    all_tournament_urls = set([t.url for t in published_tournaments])
    if to_tournament_urls:
        all_tournament_urls.update(to_tournament_urls)
    
    # Get all tournaments to display
    tournaments = Tournament.query.filter(Tournament.url.in_(list(all_tournament_urls))).order_by(Tournament.start_date.asc()).all()
    
    # Compute registered team counts per tournament
    team_counts = {}
    for t in tournaments:
        team_counts[t.url] = TeamRegistration.query.filter_by(event=t.url, status='CONFIRMED').count()

    # Compute current user's registration/payment status per tournament
    user_reg_status = {}
    if current_user.is_authenticated:
        user_type = current_user.__class__.__name__
        for t in tournaments:
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
        tournaments=tournaments,
        to_tournaments=[],  # Keep for backwards compatibility but not used
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
    page = request.args.get('page', 1, type=int)
    per_page = 50
    
    # Build base query
    if search:
        query = Player.query.filter(Player.name.contains(search) | Player.id.contains(search))
    else:
        query = Player.query
    
    # Get total count for pagination
    total = query.count()
    total_pages = (total + per_page - 1) // per_page  # Ceiling division
    
    # Apply pagination
    offset = (page - 1) * per_page
    players = query.order_by(Player.name.asc()).offset(offset).limit(per_page).all()
    
    return render_template('players.html', 
                         players=players, 
                         page=page, 
                         total_pages=total_pages, 
                         total=total,
                         search=search)


@bp.route('/about')
def about():
    """About page explaining Arctos."""
    return render_template('about.html')


@bp.route('/sitemap.xml')
def sitemap():
    """Generate XML sitemap for search engines."""
    from flask import request
    
    # Get base URL from request
    base_url = request.url_root.rstrip('/')
    
    # Static pages to include
    urls = [
        {
            'loc': base_url + url_for('main.index'),
            'changefreq': 'daily',
            'priority': '1.0'
        },
        {
            'loc': base_url + url_for('auth.login'),
            'changefreq': 'monthly',
            'priority': '0.8'
        },
        {
            'loc': base_url + url_for('main.teams'),
            'changefreq': 'daily',
            'priority': '0.9'
        },
        {
            'loc': base_url + url_for('main.players'),
            'changefreq': 'daily',
            'priority': '0.9'
        },
        {
            'loc': base_url + url_for('matches.stones_player'),
            'changefreq': 'monthly',
            'priority': '0.9'
        },
        {
            'loc': base_url + url_for('tournaments.new_tournament'),
            'changefreq': 'monthly',
            'priority': '0.7'
        },
        {
            'loc': base_url + url_for('main.about'),
            'changefreq': 'monthly',
            'priority': '0.6'
        },
    ]
    
    # Generate XML
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    
    for url_data in urls:
        xml += '  <url>\n'
        xml += f'    <loc>{url_data["loc"]}</loc>\n'
        xml += f'    <changefreq>{url_data["changefreq"]}</changefreq>\n'
        xml += f'    <priority>{url_data["priority"]}</priority>\n'
        xml += '  </url>\n'
    
    xml += '</urlset>'
    
    return Response(xml, mimetype='application/xml')


@bp.route('/robots.txt')
def robots():
    """Generate robots.txt file pointing to sitemap."""
    from flask import request
    
    base_url = request.url_root.rstrip('/')
    sitemap_url = base_url + url_for('main.sitemap')
    
    robots_txt = f"""User-agent: *
Allow: /

Sitemap: {sitemap_url}
"""
    
    return Response(robots_txt, mimetype='text/plain')


@bp.route('/docs')
def docs():
    """User documentation page."""
    import os
    from pathlib import Path
    
    # Read the markdown file
    docs_path = Path(__file__).parent.parent.parent / 'docs' / 'docs.md'
    with open(docs_path, 'r', encoding='utf-8') as f:
        markdown_content = f.read()
    return render_template('docs.html', markdown_content=markdown_content)

