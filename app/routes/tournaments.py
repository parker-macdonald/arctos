"""
Tournament management routes.
"""
from flask import Blueprint, render_template, request, redirect, flash, jsonify
from flask_login import login_required, current_user
from datetime import datetime
from models import (
    Tournament, Match, Field, Tag, TeamRegistration, PlayerRegistration,
    Team, TO, db
)
from app.utils.helpers import check_tournament_access, resolve_team_name_to_id
from app.filters import is_head_ref

bp = Blueprint('tournaments', __name__)


@bp.route('/new-tournament')
@login_required
def new_tournament():
    """Create new tournament page."""
    return render_template('new_tournament.html')


@bp.route('/create-tournament', methods=['POST'])
@login_required
def create_tournament():
    """Create a new tournament."""
    name = request.form['name']
    url = request.form['url']
    
    if Tournament.query.filter_by(url=url).first():
        flash('Tournament URL already exists', 'error')
        return redirect('/new-tournament')
    
    tournament = Tournament(
        url=url,
        name=name,
        start_date=datetime.utcnow(),
        end_date=None
    )
    
    db.session.add(tournament)
    
    to_entry = TO(
        user_id=current_user.id,
        user_type=current_user.__class__.__name__.lower(),
        event=url
    )
    db.session.add(to_entry)
    db.session.commit()
    
    flash(f'Tournament "{name}" created successfully!', 'success')
    return redirect(f'/{url}')


@bp.route('/<tournament_url>')
def tournament_home(tournament_url):
    """Tournament homepage."""
    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()
    
    if not tournament.published:
        if not current_user.is_authenticated:
            flash('This tournament is not yet published', 'error')
            return redirect('/')
        
        is_to = TO.query.filter_by(
            user_id=current_user.id, 
            user_type=current_user.__class__.__name__.lower(),
            event=tournament_url
        ).first()
        
        if not is_to:
            flash('This tournament is not yet published', 'error')
            return redirect('/')
    
    team_registrations = TeamRegistration.query.filter_by(
        event=tournament_url,
        status='CONFIRMED'
    ).all()
    
    teams_with_counts = []
    for team_reg in team_registrations:
        player_count = PlayerRegistration.query.filter_by(
            event=tournament_url,
            team=team_reg.team,
            status='CONFIRMED'
        ).count()
        
        teams_with_counts.append({
            'team_registration': team_reg,
            'player_count': player_count
        })
    
    unattached_players = []
    player_registrations = PlayerRegistration.query.filter_by(
        event=tournament_url,
        team=None,
        status='CONFIRMED'
    ).all()
    
    for player_reg in player_registrations:
        from models import Player
        player = Player.query.get(player_reg.player)
        if player:
            unattached_players.append({
                'registration': player_reg,
                'player': player
            })
    
    to_entries = TO.query.filter_by(event=tournament_url).all()

    is_current_team_registered = False
    is_current_player_registered = False
    if current_user.is_authenticated:
        if current_user.__class__.__name__ == 'Team':
            is_current_team_registered = TeamRegistration.query.filter_by(
                event=tournament_url,
                team=current_user.id,
                status='CONFIRMED'
            ).first() is not None
        elif current_user.__class__.__name__ == 'Player':
            is_current_player_registered = PlayerRegistration.query.filter_by(
                event=tournament_url,
                player=current_user.id
            ).filter(
                PlayerRegistration.status.in_(['PENDING_TEAM_APPROVAL', 'CONFIRMED'])
            ).first() is not None

    return render_template(
        'tournament_home.html',
        tournament=tournament,
        teams_with_counts=teams_with_counts,
        unattached_players=unattached_players,
        to_entries=to_entries,
        is_current_team_registered=is_current_team_registered,
        is_current_player_registered=is_current_player_registered,
    )


@bp.route('/<tournament_url>/schedule')
def tournament_schedule(tournament_url):
    """Tournament schedule page."""
    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()
    
    is_head_ref_flag = False
    if current_user.is_authenticated and current_user.__class__.__name__ == 'Player':
        is_head_ref_flag = tournament.head_refs and current_user.id.lower() in [ref.strip().lower() for ref in tournament.head_refs.split(',')]
    
    if not tournament.schedule_published:
        if not current_user.is_authenticated:
            flash('The tournament schedule is not yet published', 'error')
            return redirect(f'/{tournament_url}')
        
        is_to = TO.query.filter_by(
            user_id=current_user.id, 
            user_type=current_user.__class__.__name__.lower(),
            event=tournament_url
        ).first()
        
        if not is_to and not is_head_ref_flag:
            flash('The tournament schedule is not yet published', 'error')
            return redirect(f'/{tournament_url}')
    
    matches = Match.query.filter_by(event=tournament_url).order_by(Match.nominal_start_time).all()
    return render_template('tournament_schedule.html', tournament=tournament, matches=matches, is_head_ref=is_head_ref_flag)


@bp.route('/<tournament_url>/results')
def tournament_results(tournament_url):
    """Tournament results page."""
    has_access, tournament = check_tournament_access(tournament_url)
    if not has_access or not tournament:
        return redirect('/')
    
    from models import Point
    matches = Match.query.filter_by(event=tournament_url, status='COMPLETED').all()
    points_by_match = {}
    if matches:
        match_ids = [m.uuid for m in matches]
        all_points = Point.query.filter(Point.match.in_(match_ids)).all()
        for p in all_points:
            points_by_match.setdefault(p.match, []).append(p)
    return render_template('tournament_results.html', tournament=tournament, matches=matches, points_by_match=points_by_match)


@bp.route('/<tournament_url>/settings')
@login_required
def tournament_settings(tournament_url):
    """Tournament settings page."""
    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()
    
    to_entry = TO.query.filter_by(
        user_id=current_user.id,
        user_type=current_user.__class__.__name__.lower(),
        event=tournament_url
    ).first()
    
    if not to_entry:
        flash('You do not have permission to access tournament settings', 'error')
        return redirect(f'/{tournament_url}')
    
    return render_template('tournament_settings.html', tournament=tournament)


@bp.route('/<tournament_url>/setup')
@login_required
def tournament_setup(tournament_url):
    """Tournament setup page."""
    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()
    
    to_entry = TO.query.filter_by(
        user_id=current_user.id,
        user_type=current_user.__class__.__name__.lower(),
        event=tournament_url
    ).first()
    
    if not to_entry:
        flash('You do not have permission to access tournament setup', 'error')
        return redirect(f'/{tournament_url}')
    
    matches = Match.query.filter_by(event=tournament_url).order_by(Match.nominal_start_time).all()
    fields = Field.query.filter_by(event=tournament_url).all()
    tags = Tag.query.filter_by(event=tournament_url).all()
    team_registrations = TeamRegistration.query.filter_by(event=tournament_url).all()
    return render_template('tournament_setup.html', tournament=tournament, matches=matches, fields=fields, tags=tags, team_registrations=team_registrations)


@bp.route('/<tournament_url>/register')
def tournament_register(tournament_url):
    """Tournament registration page."""
    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()
    if not tournament.registration_open:
        flash('Registration is not open for this tournament', 'warning')
        return redirect(f'/{tournament_url}')
    
    team_registrations = TeamRegistration.query.filter_by(
        event=tournament_url,
        status='CONFIRMED'
    ).all()
    
    registered_teams = []
    for team_reg in team_registrations:
        team = Team.query.get(team_reg.team)
        if team:
            registered_teams.append({
                'team': team,
                'pseudonym': team_reg.pseudonym
            })
    
    return render_template('tournament_register.html', tournament=tournament, registered_teams=registered_teams)


@bp.route('/<tournament_url>/update-settings', methods=['POST'])
@login_required
def update_tournament_settings(tournament_url):
    """Update tournament settings."""
    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()
    
    tournament.name = request.form['name']
    tournament.location = request.form.get('location', '')
    tournament.num_fields = int(request.form.get('num_fields', 1))
    tournament.n_max_teams = int(request.form.get('n_max_teams', 0) or 0) or None
    tournament.max_team_size_roster = int(request.form.get('max_team_size_roster', 0) or 0) or None
    tournament.max_team_size_field = int(request.form.get('max_team_size_field', 0) or 0) or None
    tournament.team_reg_fee = float(request.form.get('team_reg_fee', 0))
    tournament.player_reg_fee = float(request.form.get('player_reg_fee', 0))
    tournament.about = request.form.get('about', '')
    tournament.terms_link = request.form.get('terms_link', '')
    tournament.head_refs = request.form.get('head_refs', '')
    tournament.published = 'published' in request.form
    tournament.schedule_published = 'schedule_published' in request.form
    tournament.registration_open = 'registration_open' in request.form
    
    if request.form.get('start_date'):
        tournament.start_date = datetime.strptime(request.form['start_date'], '%Y-%m-%d')
    
    if request.form.get('end_date'):
        tournament.end_date = datetime.strptime(request.form['end_date'], '%Y-%m-%d')
    else:
        tournament.end_date = None
    
    db.session.commit()
    flash('Tournament settings updated successfully!', 'success')
    return redirect(f'/{tournament_url}/settings')


@bp.route('/<tournament_url>/add-match', methods=['POST'])
@login_required
def add_match(tournament_url):
    """Add a match to tournament."""
    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()
    
    team1_name = request.form.get('team1', '')
    team2_name = request.form.get('team2', '')
    
    team1_id = resolve_team_name_to_id(team1_name, tournament_url)
    team2_id = resolve_team_name_to_id(team2_name, tournament_url)
    
    match = Match(
        name=request.form['match_name'],
        event=tournament_url,
        field=request.form.get('field', ''),
        team1=team1_id,
        team1_initial=team1_name,
        team2=team2_id,
        team2_initial=team2_name,
        type=request.form.get('match_type', 'SETS'),
        nsets=int(request.form.get('nsets', 3)),
        nominal_length=int(request.form.get('length', 60)),
        dynamic=request.form.get('dynamic') == 'true',
        refs_initial=request.form.get('refs', '')
    )
    
    if request.form.get('start_time'):
        match.nominal_start_time = datetime.strptime(request.form['start_time'], '%Y-%m-%dT%H:%M')
    
    db.session.add(match)
    db.session.commit()
    
    flash('Match added successfully!', 'success')
    return redirect(f'/{tournament_url}/setup')


@bp.route('/<tournament_url>/add-field', methods=['POST'])
@login_required
def add_field(tournament_url):
    """Add a field to tournament."""
    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()
    
    field = Field(
        event=tournament_url,
        name=request.form['field_name'],
        camera=request.form.get('camera', '')
    )
    
    db.session.add(field)
    db.session.commit()
    
    current_field_count = Field.query.filter_by(event=tournament_url).count()
    if current_field_count >= tournament.num_fields:
        flash(f'Maximum number of fields ({tournament.num_fields}) reached', 'error')
        return redirect(f'/{tournament_url}/setup')
    
    flash('Field added successfully!', 'success')
    return redirect(f'/{tournament_url}/setup')


@bp.route('/<tournament_url>/edit-field')
@login_required
def edit_field(tournament_url):
    """Edit field page."""
    field_id = request.args.get('id')
    if not field_id:
        flash('Field ID is required', 'error')
        return redirect(f'/{tournament_url}/setup')
    
    field = Field.query.get_or_404(field_id)
    return render_template('edit_field.html', tournament_url=tournament_url, field=field)


@bp.route('/<tournament_url>/update-field', methods=['POST'])
@login_required
def update_field(tournament_url):
    """Update field."""
    field_id = request.form.get('field_id')
    if not field_id:
        flash('Field ID is required', 'error')
        return redirect(f'/{tournament_url}/setup')
    
    field = Field.query.get_or_404(field_id)
    field.name = request.form['field_name']
    field.camera = request.form.get('camera', '')
    
    db.session.commit()
    flash('Field updated successfully!', 'success')
    return redirect(f'/{tournament_url}/setup')


@bp.route('/<tournament_url>/delete-field', methods=['POST'])
@login_required
def delete_field(tournament_url):
    """Delete field."""
    field_id = request.form.get('field_id')
    if not field_id:
        flash('Field ID is required', 'error')
        return redirect(f'/{tournament_url}/setup')
    
    field = Field.query.get_or_404(field_id)
    db.session.delete(field)
    db.session.commit()
    flash('Field deleted successfully!', 'success')
    return redirect(f'/{tournament_url}/setup')


@bp.route('/<tournament_url>/add-tag', methods=['POST'])
@login_required
def add_tag(tournament_url):
    """Add a tag to tournament."""
    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()
    
    tag = Tag(
        event=tournament_url,
        name=request.form['tag_name']
    )
    
    db.session.add(tag)
    db.session.commit()
    
    flash('Tag added successfully!', 'success')
    return redirect(f'/{tournament_url}/setup')


@bp.route('/<tournament_url>/edit-tag')
@login_required
def edit_tag(tournament_url):
    """Edit tag page."""
    tag_id = request.args.get('id')
    if not tag_id:
        flash('Tag ID is required', 'error')
        return redirect(f'/{tournament_url}/setup')
    
    tag = Tag.query.get_or_404(tag_id)
    return render_template('edit_tag.html', tournament_url=tournament_url, tag=tag)


@bp.route('/<tournament_url>/update-tag', methods=['POST'])
@login_required
def update_tag(tournament_url):
    """Update tag."""
    tag_id = request.form.get('tag_id')
    if not tag_id:
        flash('Tag ID is required', 'error')
        return redirect(f'/{tournament_url}/setup')
    
    tag = Tag.query.get_or_404(tag_id)
    tag.name = request.form['tag_name']
    
    db.session.commit()
    flash('Tag updated successfully!', 'success')
    return redirect(f'/{tournament_url}/setup')


@bp.route('/<tournament_url>/delete-tag', methods=['POST'])
@login_required
def delete_tag(tournament_url):
    """Delete tag."""
    tag_id = request.form.get('tag_id')
    if not tag_id:
        flash('Tag ID is required', 'error')
        return redirect(f'/{tournament_url}/setup')
    
    tag = Tag.query.get_or_404(tag_id)
    db.session.delete(tag)
    db.session.commit()
    flash('Tag deleted successfully!', 'success')
    return redirect(f'/{tournament_url}/setup')


@bp.route('/<tournament_url>/edit-match')
@login_required
def edit_match(tournament_url):
    """Edit match page."""
    match_id = request.args.get('id')
    if not match_id:
        flash('Match ID is required', 'error')
        return redirect(f'/{tournament_url}/setup')
    
    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()
    match = Match.query.get_or_404(match_id)
    fields = Field.query.filter_by(event=tournament_url).all()
    tags = Tag.query.filter_by(event=tournament_url).all()
    return render_template('edit_match.html', tournament=tournament, match=match, fields=fields, tags=tags)


@bp.route('/<tournament_url>/update-match', methods=['POST'])
@login_required
def update_match(tournament_url):
    """Update match."""
    match_id = request.form.get('match_id')
    if not match_id:
        flash('Match ID is required', 'error')
        return redirect(f'/{tournament_url}/setup')
    
    match = Match.query.get_or_404(match_id)
    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()
    
    team1_name = request.form.get('team1', '')
    team2_name = request.form.get('team2', '')
    
    team1_id = resolve_team_name_to_id(team1_name, tournament_url)
    team2_id = resolve_team_name_to_id(team2_name, tournament_url)
    
    match.name = request.form['match_name']
    match.field = request.form.get('field', '')
    match.team1 = team1_id
    match.team1_initial = team1_name
    match.team2 = team2_id
    match.team2_initial = team2_name
    match.type = request.form.get('match_type', 'SETS')
    match.nsets = int(request.form.get('nsets', 3))
    match.nominal_length = int(request.form.get('length', 60))
    match.dynamic = request.form.get('dynamic') == 'true'
    match.refs_initial = request.form.get('refs', '')
    
    if request.form.get('start_time'):
        match.nominal_start_time = datetime.strptime(request.form['start_time'], '%Y-%m-%dT%H:%M')
    else:
        match.nominal_start_time = None
    
    db.session.commit()
    flash('Match updated successfully!', 'success')
    return redirect(f'/{tournament_url}/setup')


@bp.route('/<tournament_url>/update-tags', methods=['POST'])
@login_required
def update_tags(tournament_url):
    """Update match tags."""
    match_id = request.form.get('match_id')
    if not match_id:
        return jsonify({'success': False, 'error': 'Match ID required'})
    
    match = Match.query.get_or_404(match_id)
    tag_ids = request.form.getlist('tags[]')
    
    # Clear existing tags (assuming a many-to-many relationship)
    # If tags are stored differently, adjust this
    from models import Tag
    match_tags = Tag.query.filter(Tag.event == tournament_url).filter(Tag.id.in_(tag_ids)).all()
    
    # Update match tags based on your data model
    # This is a placeholder - adjust based on your actual tag relationship
    db.session.commit()
    
    return jsonify({'success': True})


@bp.route('/<tournament_url>/api/autocomplete')
def tournament_autocomplete(tournament_url):
    """Autocomplete endpoint for tournament setup."""
    query = request.args.get('q', '').lower()
    if not query:
        return jsonify([])
    
    # Autocomplete teams
    team_regs = TeamRegistration.query.filter_by(event=tournament_url).all()
    suggestions = []
    
    for reg in team_regs:
        if query in reg.pseudonym.lower():
            suggestions.append({
                'type': 'team',
                'value': reg.pseudonym,
                'id': reg.team
            })
    
    # Autocomplete match names for dynamic references
    matches = Match.query.filter_by(event=tournament_url).all()
    for match in matches:
        if query in match.name.lower():
            suggestions.append({
                'type': 'match',
                'value': match.name,
                'id': match.uuid
            })
    
    return jsonify(suggestions[:10])  # Limit to 10 suggestions

