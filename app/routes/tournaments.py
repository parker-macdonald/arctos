"""
Tournament management routes.
"""
from flask import Blueprint, render_template, request, redirect, flash, jsonify
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from models import (
    Tournament, Match, Field, Tag, TeamRegistration, PlayerRegistration,
    Team, TO, db
)
from app.utils.helpers import check_tournament_access, resolve_team_name_to_id, validate_permission_key
from app.utils.scheduling import compute_dynamic_match_nominal_start_time, validate_match_input, update_match_sequence, recompute_all_match_times, detect_match_conflicts
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
    permission_key = request.form.get('permission_key', '').strip()
    
    # Validate permission key
    if not validate_permission_key(url, permission_key):
        flash('Invalid permission key. Please contact reid@xz.ax to request a permission key for your tournament URL slug.', 'error')
        return redirect('/new-tournament')
    
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
        
        team = Team.query.get(team_reg.team)
        teams_with_counts.append({
            'team_registration': team_reg,
            'player_count': player_count,
            'team': team
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
    fields = Field.query.filter_by(event=tournament_url).order_by(Field.name).all()

    # Optional filters/highlighting
    filter_field = request.args.get('field', '').strip() or None
    highlight_team = request.args.get('team', '').strip() or None

    # Get all teams for autocomplete (team IDs and pseudonyms)
    from models import TeamRegistration
    team_registrations = TeamRegistration.query.filter_by(
        event=tournament_url,
        status='CONFIRMED'
    ).all()
    
    # Build list of team options (ID and pseudonym)
    team_options = []
    seen_teams = set()
    for team_reg in team_registrations:
        if team_reg.team not in seen_teams:
            team_options.append({
                'id': team_reg.team,
                'pseudonym': team_reg.pseudonym
            })
            seen_teams.add(team_reg.team)
    
    # Also include any team IDs/pseudonyms from match initial values
    for match in matches:
        if match.team1_initial and match.team1_initial not in seen_teams:
            # Check if it's a dependency reference (ends with "winner" or "loser")
            if not (match.team1_initial.endswith(' winner') or match.team1_initial.endswith(' loser')):
                team_options.append({
                    'id': match.team1_initial,
                    'pseudonym': match.team1_initial
                })
                seen_teams.add(match.team1_initial)
        if match.team2_initial and match.team2_initial not in seen_teams:
            if not (match.team2_initial.endswith(' winner') or match.team2_initial.endswith(' loser')):
                team_options.append({
                    'id': match.team2_initial,
                    'pseudonym': match.team2_initial
                })
                seen_teams.add(match.team2_initial)

    return render_template(
        'tournament_schedule.html',
        tournament=tournament,
        matches=matches,
        fields=fields,
        is_head_ref=is_head_ref_flag,
        filter_field=filter_field,
        highlight_team=highlight_team,
        team_options=team_options,
    )


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
    
    from sqlalchemy.orm import joinedload
    matches = Match.query.options(
        joinedload(Match.previous_match_obj),
        joinedload(Match.next_match_obj)
    ).filter_by(event=tournament_url).order_by(Match.nominal_start_time).all()
    fields = Field.query.filter_by(event=tournament_url).all()
    tags = Tag.query.filter_by(event=tournament_url).all()
    team_registrations = TeamRegistration.query.filter_by(event=tournament_url).all()
    
    # Detect conflicts across all matches
    conflicts = detect_match_conflicts(tournament_url)
    
    return render_template('tournament_setup.html', tournament=tournament, matches=matches, fields=fields, tags=tags, team_registrations=team_registrations, conflicts=conflicts)


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
    
    # Check if BREAK or JOIN is selected from the Match Type dropdown (renamed from 'dynamic')
    match_type_value = request.form.get('dynamic', '')
    
    if match_type_value == 'BREAK':
        match_type = 'BREAK'
        is_dynamic = True  # BREAK is always dynamic
        nominal_length = int(request.form.get('length', 60))
    elif match_type_value == 'JOIN':
        match_type = 'JOIN'
        is_dynamic = True  # JOIN is always dynamic
        nominal_length = 0
    else:
        match_type = request.form.get('match_type', 'SETS')
        is_dynamic = match_type_value == 'true'
        nominal_length = int(request.form.get('length', 60))
    
    # BREAK and JOIN matches don't have teams/refs
    if match_type in ('BREAK', 'JOIN'):
        team1_id = None
        team1_name = ''
        team2_id = None
        team2_name = ''
        refs_initial = ''
    else:
        team1_name = request.form.get('team1', '')
        team2_name = request.form.get('team2', '')
        team1_id = resolve_team_name_to_id(team1_name, tournament_url)
        team2_id = resolve_team_name_to_id(team2_name, tournament_url)
        refs_initial = request.form.get('refs', '')
    
    match = Match(
        name=request.form['match_name'],
        event=tournament_url,
        field=request.form.get('field', ''),
        team1=team1_id,
        team1_initial=team1_name,
        team2=team2_id,
        team2_initial=team2_name,
        type=match_type,
        nsets=int(request.form.get('nsets', 3)) if match_type not in ('BREAK', 'JOIN') else None,
        nominal_length=nominal_length,
        dynamic=is_dynamic,
        refs_initial=refs_initial
    )
    
    # For dynamic matches, set previous_match from form and compute start time from it
    # For static matches, use the provided start_time
    if is_dynamic:
        # Get previous_match from form
        prev_match_id = request.form.get('previous_match', '')
        if prev_match_id:
            match.previous_match = prev_match_id
        match.nominal_start_time = compute_dynamic_match_nominal_start_time(match, tournament_url)
    else:
        # Static matches can have manual start time
        if request.form.get('start_time'):
            match.nominal_start_time = datetime.strptime(request.form['start_time'], '%Y-%m-%dT%H:%M')
    
    # Validate inputs and constraints
    ok, err = validate_match_input(match, tournament_url)
    if not ok:
        flash(err, 'error')
        return redirect(f'/{tournament_url}/setup')
    
    db.session.add(match)
    db.session.flush()  # Flush to get UUID before updating sequence
    
    # Recompute all match times (for all dynamic matches that depend on this one)
    recompute_all_match_times(tournament_url)
    
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
    matches = Match.query.filter_by(event=tournament_url).order_by(Match.nominal_start_time).all()
    fields = Field.query.filter_by(event=tournament_url).all()
    tags = Tag.query.filter_by(event=tournament_url).all()
    return render_template('edit_match.html', tournament=tournament, match=match, matches=matches, fields=fields, tags=tags)


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
    
    # Check if BREAK or JOIN is selected from the Match Type dropdown (renamed from 'dynamic')
    match_type_value = request.form.get('dynamic', '')
    
    if match_type_value == 'BREAK':
        match_type = 'BREAK'
        is_dynamic = True  # BREAK is always dynamic
    elif match_type_value == 'JOIN':
        match_type = 'JOIN'
        is_dynamic = True  # JOIN is always dynamic
    else:
        match_type = request.form.get('match_type', match.type)
        is_dynamic = match_type_value == 'true'
    
    # BREAK and JOIN matches don't have teams/refs
    if match_type in ('BREAK', 'JOIN'):
        team1_id = None
        team1_name = ''
        team2_id = None
        team2_name = ''
        refs_initial = ''
    else:
        team1_name = request.form.get('team1', '')
        team2_name = request.form.get('team2', '')
        team1_id = resolve_team_name_to_id(team1_name, tournament_url)
        team2_id = resolve_team_name_to_id(team2_name, tournament_url)
        refs_initial = request.form.get('refs', '')
    
    match.name = request.form['match_name']
    match.field = request.form.get('field', '')
    match.team1 = team1_id
    match.team1_initial = team1_name
    match.team2 = team2_id
    match.team2_initial = team2_name
    match.type = match_type
    
    # BREAK and JOIN don't have nsets
    if match_type not in ('BREAK', 'JOIN'):
        match.nsets = int(request.form.get('nsets', 3))
    else:
        match.nsets = None
    
    # JOIN has zero length, BREAK can have length
    if match_type == 'JOIN':
        match.nominal_length = 0
    elif match_type == 'BREAK':
        match.nominal_length = int(request.form.get('length', match.nominal_length or 60))
    else:
        match.nominal_length = int(request.form.get('length', match.nominal_length or 60))
    
    match.dynamic = is_dynamic
    match.refs_initial = refs_initial
    
    # For dynamic matches, set previous_match from form and compute start time from it
    # For static matches, ensure previous_match is cleared and use provided start_time
    if is_dynamic:
        # Get previous_match from form
        prev_match_id = request.form.get('previous_match', '')
        old_prev = match.previous_match
        if prev_match_id:
            match.previous_match = prev_match_id
            # Try to set the other match's next_match to this one if no conflict
            try:
                prev_m = Match.query.filter_by(uuid=prev_match_id, event=tournament_url).first()
                if prev_m and (not prev_m.next_match or prev_m.next_match == match.uuid):
                    prev_m.next_match = match.uuid
                # If previous changed, clear old previous's next pointer if it pointed to this match
                if old_prev and old_prev != prev_match_id:
                    old_prev_m = Match.query.filter_by(uuid=old_prev, event=tournament_url).first()
                    if old_prev_m and old_prev_m.next_match == match.uuid:
                        old_prev_m.next_match = None
            except Exception:
                pass
        else:
            match.previous_match = None
        match.nominal_start_time = compute_dynamic_match_nominal_start_time(match, tournament_url)
    else:
        # Static matches can have manual start time
        match.previous_match = None
        if request.form.get('start_time'):
            match.nominal_start_time = datetime.strptime(request.form['start_time'], '%Y-%m-%dT%H:%M')
        else:
            match.nominal_start_time = None
    
    # Validate inputs and constraints
    ok, err = validate_match_input(match, tournament_url)
    if not ok:
        flash(err, 'error')
        return redirect(f'/{tournament_url}/edit-match?id={match_id}')
    
    db.session.flush()  # Flush before updating sequence
    
    # Recompute all match times (for all dynamic matches that depend on this one)
    recompute_all_match_times(tournament_url)
    
    db.session.commit()
    flash('Match updated successfully!', 'success')
    return redirect(f'/{tournament_url}/setup')


@bp.route('/<tournament_url>/update-tags', methods=['POST'])
@login_required
def update_tags(tournament_url):
    """Update all matches by converting tag names to team IDs in team1_initial, team2_initial, and refs_initial."""
    from models import Tag
    
    # Get all tags for this tournament
    tags = Tag.query.filter_by(event=tournament_url).all()
    
    # Build mapping of tag names to team IDs
    tag_to_team = {}
    for tag in tags:
        form_key = f'tag_{tag.id}'
        team_id = request.form.get(form_key, '').strip()
        if team_id:
            tag_to_team[tag.name] = team_id
    
    if not tag_to_team:
        flash('No tag conversions selected', 'error')
        return redirect(f'/{tournament_url}/setup')
    
    # Get all matches for this tournament
    matches = Match.query.filter_by(event=tournament_url).all()
    updated_count = 0
    
    for match in matches:
        changed = False
        
        # Update team1_initial
        if match.team1_initial:
            initial = match.team1_initial.strip()
            if initial in tag_to_team:
                match.team1_initial = tag_to_team[initial]
                # Also set team1 if not already set
                if not match.team1:
                    match.team1 = tag_to_team[initial]
                changed = True
        
        # Update team2_initial
        if match.team2_initial:
            initial = match.team2_initial.strip()
            if initial in tag_to_team:
                match.team2_initial = tag_to_team[initial]
                # Also set team2 if not already set
                if not match.team2:
                    match.team2 = tag_to_team[initial]
                changed = True
        
        # Update refs_initial (comma-separated)
        if match.refs_initial:
            refs_list = [r.strip() for r in match.refs_initial.split(',') if r.strip()]
            updated_refs = []
            refs_changed = False
            for ref in refs_list:
                if ref in tag_to_team:
                    updated_refs.append(tag_to_team[ref])
                    refs_changed = True
                else:
                    updated_refs.append(ref)
            
            if refs_changed:
                match.refs_initial = ', '.join(updated_refs)
                # Also update refs if not already set
                if not match.refs:
                    match.refs = ', '.join([r for r in updated_refs if r])
                changed = True
        
        if changed:
            updated_count += 1
    
    db.session.commit()
    
    if updated_count > 0:
        flash(f'Successfully updated {updated_count} match(es) with tag conversions', 'success')
    else:
        flash('No matches were updated. No matches contain the selected tags.', 'info')
    
    return redirect(f'/{tournament_url}/setup')


@bp.route('/<tournament_url>/api/autocomplete')
def tournament_autocomplete(tournament_url):
    """Autocomplete endpoint for tournament setup.
    Returns a list of suggestions with fields: type, value, label, id
    """
    q_raw = request.args.get('q', '')
    query = (q_raw or '').strip().lower()

    suggestions = []
    
    # Teams registered in this tournament
    team_regs = TeamRegistration.query.filter_by(event=tournament_url).all()
    for reg in team_regs:
        pseudonym = (reg.pseudonym or '').strip()
        if not query or query in pseudonym.lower():
            suggestions.append({
                'type': 'team',
                'value': pseudonym,
                'label': pseudonym,
                'id': reg.team
            })
    
    # Tags for this tournament (by name)
    tags = Tag.query.filter_by(event=tournament_url).all() if 'Tag' in globals() or True else []
    try:
        tags = Tag.query.filter_by(event=tournament_url).all()
    except Exception:
        tags = []
    for t in tags:
        name = (t.name or '').strip()
        if not query or query in name.lower():
            suggestions.append({
                'type': 'tag',
                'value': name,
                'label': name,
                'id': t.id
            })

    # Matches in this tournament (by name)
    matches = Match.query.filter_by(event=tournament_url).all()
    for m in matches:
        name = (m.name or '').strip()
        if not query or query in name.lower():
            suggestions.append({
                'type': 'match',
                'value': name,
                'label': name,
                'id': m.uuid
            })
    
        # Also offer winner/loser variants to help dynamic references
        winner_label = f"{name} winner"
        loser_label = f"{name} loser"
        if not query or query in winner_label.lower():
            suggestions.append({
                'type': 'result',
                'value': winner_label,
                'label': winner_label,
                'id': m.uuid
            })
        if not query or query in loser_label.lower():
            suggestions.append({
                'type': 'result',
                'value': loser_label,
                'label': loser_label,
                'id': m.uuid
            })

    # Limit and return
    # When query is empty, return all suggestions (for preloading)
    # When query is provided, limit to 50 for performance
    if not query:
        return jsonify(suggestions)
    else:
        return jsonify(suggestions[:50])

