"""
Tournament management routes.
"""
from flask import Blueprint, render_template, request, redirect, flash, jsonify
from flask_login import login_required, current_user
from datetime import datetime, timedelta
import json
from models import (
    Tournament, Match, Field, Tag, TeamRegistration, PlayerRegistration,
    Team, TO, db
)
from app.utils.helpers import check_tournament_access, resolve_team_name_to_id, validate_permission_key
from app.utils.scheduling import compute_dynamic_match_nominal_start_time, validate_match_input, recompute_all_match_times, detect_match_conflicts
from app.filters import is_head_ref

bp = Blueprint('tournaments', __name__)

def update_match_previous_link(match: Match, prev_match_id: str, tournament_url: str, is_new: bool = False) -> None:
    """
    Update the previous_match link for a match, maintaining a doubly linked list structure.
    
    When inserting a match after prev_match, if prev_match already has a next_match:
    1. Store the old next_match of prev_match
    2. Set the current match's previous_match to prev_match
    3. Set prev_match's next_match to the current match
    4. Set the current match's next_match to the old next_match (if it existed)
    5. Set the old next_match's previous_match to the current match (if it existed)
    6. If updating (not new), handle cleanup of old previous_match's next_match
    
    This properly inserts the match into the chain: ... -> prev_match -> match -> old_next_match -> ...
    
    Args:
        match: The match to update
        prev_match_id: UUID of the match to set as previous_match
        tournament_url: Tournament URL for validation
        is_new: True if this is a new match, False if updating existing match
    """
    prev_match = Match.query.filter_by(uuid=prev_match_id, event=tournament_url).first()
    if not prev_match:
        return
    
    # Store old previous_match and next_match for cleanup (only for updates)
    old_prev_id = match.previous_match if not is_new else None
    old_next_id = match.next_match if not is_new else None
    
    # Store the old next_match of prev_match (before we change it)
    prev_match_old_next_id = prev_match.next_match
    
    # Set the current match's previous_match to prev_match
    match.previous_match = prev_match_id
    
    # Set prev_match's next_match to this match
    prev_match.next_match = match.uuid
    
    # If prev_match had a next_match that isn't this match, link it to this match
    if prev_match_old_next_id and prev_match_old_next_id != match.uuid:
        prev_match_old_next = Match.query.filter_by(uuid=prev_match_old_next_id, event=tournament_url).first()
        if prev_match_old_next:
            # Set the current match's next_match to the old next_match
            match.next_match = prev_match_old_next_id
            # Set the old next_match's previous_match to this match
            prev_match_old_next.previous_match = match.uuid
    else:
        # No old next_match from prev_match, so clear this match's next_match
        match.next_match = None
    
    # If updating and had an old previous_match, handle cleanup
    if old_prev_id and old_prev_id != prev_match_id:
        old_prev_match = Match.query.filter_by(uuid=old_prev_id, event=tournament_url).first()
        if old_prev_match:
            # If old_prev_match's next_match pointed to this match, we need to update it
            if old_prev_match.next_match == match.uuid:
                # The old previous match's next should now point to this match's old next (if any)
                old_prev_match.next_match = old_next_id if old_next_id != old_prev_id else None
                # If we set old_prev_match.next_match to something, update that match's previous_match
                if old_prev_match.next_match:
                    old_next_of_old_prev = Match.query.filter_by(uuid=old_prev_match.next_match, event=tournament_url).first()
                    if old_next_of_old_prev:
                        old_next_of_old_prev.previous_match = old_prev_id
    
    # If updating and had an old next_match that we didn't preserve, handle cleanup
    if old_next_id and old_next_id != match.next_match:
        old_next_match = Match.query.filter_by(uuid=old_next_id, event=tournament_url).first()
        if old_next_match and old_next_match.previous_match == match.uuid:
            # This match's old next_match no longer has this match as its previous
            old_next_match.previous_match = None

def is_not_TO(tournament_url, message='You are not a TO, fuck off!!1!!1'):
    if not TO.query.filter_by(user_id=current_user.id,
                              user_type=current_user.__class__.__name__.lower(),
                              event=tournament_url).first():
        flash(message, 'error')
        return True
    return False
    
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
    
    from app.utils.helpers import can_head_ref_match
    is_head_ref_flag = False
    if current_user.is_authenticated and current_user.__class__.__name__ == 'Player':
        is_head_ref_flag = can_head_ref_match(tournament_url, current_user.id, match=None)
    
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
    if is_not_TO(tournament_url):
        return redirect(f'/{tournament_url}')
    
    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()
    
    to_entry = TO.query.filter_by(
        user_id=current_user.id,
        user_type=current_user.__class__.__name__.lower(),
        event=tournament_url
    ).first()
    
    if not to_entry:
        flash('You do not have permission to access tournament settings', 'error')
        return redirect(f'/{tournament_url}')
    
    # Get all TOs for this tournament with their user info
    from models import Player, Team
    to_entries = TO.query.filter_by(event=tournament_url).all()
    tos_with_info = []
    for to_entry in to_entries:
        if to_entry.user_type == 'player':
            user = Player.query.get(to_entry.user_id)
            user_name = user.name if user else to_entry.user_id
        else:  # team
            user = Team.query.get(to_entry.user_id)
            user_name = user.name if user else to_entry.user_id
        
        tos_with_info.append({
            'to': to_entry,
            'user': user,
            'user_name': user_name,
            'is_current_user': to_entry.user_id == current_user.id and to_entry.user_type == current_user.__class__.__name__.lower()
        })
    
    return render_template('tournament_settings.html', tournament=tournament, tos_with_info=tos_with_info)


@bp.route('/<tournament_url>/setup')
@login_required
def tournament_setup(tournament_url):
    """Tournament setup page."""
    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()
    
    if is_not_TO(tournament_url):
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
    if is_not_TO(tournament_url):
        return redirect(f'/{tournament_url}')
    
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
    tournament.head_refs_allowed_list = request.form.get('head_refs_allowed_list', '')
    tournament.head_refs_allow_reffing_teams = 'head_refs_allow_reffing_teams' in request.form
    tournament.head_refs_allow_anyone = 'head_refs_allow_anyone' in request.form
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
    if is_not_TO(tournament_url):
        return redirect(f'/{tournament_url}')
        
    # Check if BREAK or JOIN is selected from the Match Type dropdown (renamed from 'dynamic')
    match_type_value = request.form.get('dynamic', '')
    
    if match_type_value == 'BREAK':
        schedule_type = 'BREAK'
        set_type = 'SETS'  # Not used for BREAK, but set a default
        nominal_length = int(request.form.get('length', 60))
    elif match_type_value == 'JOIN':
        schedule_type = 'JOIN'
        set_type = 'SETS'  # Not used for JOIN, but set a default
        nominal_length = 0
    else:
        schedule_type = 'DYNAMIC' if match_type_value == 'true' else 'STATIC'
        set_type = request.form.get('match_type', 'SETS')
        nominal_length = int(request.form.get('length', 60))
    
    # BREAK and JOIN matches don't have teams/refs
    if schedule_type in ('BREAK', 'JOIN'):
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
    
    ribbon = request.form.get('ribbon', '') == 'on'  # Checkbox value
    
    match = Match(
        name=request.form['match_name'],
        event=tournament_url,
        field=request.form.get('field', ''),
        team1=team1_id,
        team1_initial=team1_name,
        team2=team2_id,
        team2_initial=team2_name,
        schedule_type=schedule_type,
        set_type=set_type,
        ribbon=ribbon,
        nsets=int(request.form.get('nsets', 3)) if schedule_type not in ('BREAK', 'JOIN') else None,
        nominal_length=nominal_length,
        refs_initial=refs_initial
    )
    
    # Validate inputs and constraints (before adding to session)
    ok, err = validate_match_input(match, tournament_url)
    if not ok:
        flash(err, 'error')
        return redirect(f'/{tournament_url}/setup')
    
    db.session.add(match)
    db.session.flush()  # Flush to get UUID before updating links
    
    # For dynamic matches, set previous_match from form and compute start time from it
    # For static matches, use the provided start_time
    if schedule_type != 'STATIC':
        # Get previous_match from form
        prev_match_id = request.form.get('previous_match', '')
        if prev_match_id:
            # Update doubly linked list: insert this match after prev_match
            update_match_previous_link(match, prev_match_id, tournament_url, is_new=True)
        else:
            match.previous_match = None
        match.nominal_start_time = compute_dynamic_match_nominal_start_time(match, tournament_url)
    else:
        # Static matches can have manual start time
        if request.form.get('start_time'):
            match.nominal_start_time = datetime.strptime(request.form['start_time'], '%Y-%m-%dT%H:%M')
    
    # Recompute all match times (for all dynamic matches that depend on this one)
    recompute_all_match_times(tournament_url)
    
    db.session.commit()
    
    flash('Match added successfully!', 'success')
    return redirect(f'/{tournament_url}/setup')


@bp.route('/<tournament_url>/add-field', methods=['POST'])
@login_required
def add_field(tournament_url):
    """Add a field to tournament."""
    if is_not_TO(tournament_url):
        return redirect(f'/{tournament_url}')
    
    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()
    
    # Get camera URLs from form (camera[] array)
    camera_urls = request.form.getlist('camera[]')
    # Filter out empty values
    camera_urls = [url.strip() for url in camera_urls if url.strip()]
    
    # Store as JSON array
    camera_value = json.dumps(camera_urls) if camera_urls else ''
    
    field = Field(
        event=tournament_url,
        name=request.form['field_name'],
        camera=camera_value
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
    if is_not_TO(tournament_url):
        return redirect(f'/{tournament_url}')
    
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
    if is_not_TO(tournament_url):
        return redirect(f'/{tournament_url}')
    
    field_id = request.form.get('field_id')
    if not field_id:
        flash('Field ID is required', 'error')
        return redirect(f'/{tournament_url}/setup')
    
    field = Field.query.get_or_404(field_id)
    old_field_name = field.name
    new_field_name = request.form['field_name']
    
    # Update field name
    field.name = new_field_name
    
    # Get camera URLs from form (camera[] array)
    camera_urls = request.form.getlist('camera[]')
    # Filter out empty values
    camera_urls = [url.strip() for url in camera_urls if url.strip()]
    
    # Get old camera URLs for comparison
    old_camera_urls = []
    if field.camera:
        from app.utils.camera_helpers import parse_camera_urls
        old_camera_urls = parse_camera_urls(field.camera)
    
    # Store as JSON array
    field.camera = json.dumps(camera_urls) if camera_urls else ''
    
    # Get all matches that reference this field (for both name and camera updates)
    # Use old field name if name changed, otherwise use current name
    field_name_for_query = old_field_name if old_field_name != new_field_name else new_field_name
    matches_to_update = Match.query.filter_by(
        event=tournament_url,
        field=field_name_for_query
    ).all()
    
    # If camera URLs changed, update matches and points that reference this field
    camera_urls_changed = old_camera_urls != camera_urls
    camera_update_count = 0
    if camera_urls_changed:
        # Build mapping from old index to new index based on URL matching
        # This handles reordering, additions, and removals
        old_to_new_index_map = {}
        for new_idx, new_url in enumerate(camera_urls):
            # Find if this URL existed in old list
            try:
                old_idx = old_camera_urls.index(new_url)
                old_to_new_index_map[str(old_idx)] = str(new_idx)
            except ValueError:
                # New URL, no mapping needed
                pass
        
        # Update matches that reference this field
        for match in matches_to_update:
            if match.camera_stream_starts:
                try:
                    stream_starts = json.loads(match.camera_stream_starts)
                    # Remap camera indices
                    new_stream_starts = {}
                    for old_idx_str, start_time in stream_starts.items():
                        if old_idx_str in old_to_new_index_map:
                            new_idx_str = old_to_new_index_map[old_idx_str]
                            new_stream_starts[new_idx_str] = start_time
                        # If old index not in map, camera was removed - don't include it
                    match.camera_stream_starts = json.dumps(new_stream_starts) if new_stream_starts else None
                    camera_update_count += 1
                except (json.JSONDecodeError, TypeError) as e:
                    print(f"Error updating camera_stream_starts for match {match.uuid}: {e}")
                    # If parsing fails, clear it
                    match.camera_stream_starts = None
        
        # Update points that reference this field (via the match)
        # Get all points for matches on this field
        from models import Point
        from app.utils.camera_helpers import calculate_stream_timestamp
        point_update_count = 0
        for match in matches_to_update:
            points = Point.query.filter_by(match=match.uuid).all()
            
            # Get stream start times for this match
            stream_starts = {}
            if match.camera_stream_starts:
                try:
                    stream_starts = json.loads(match.camera_stream_starts)
                except (json.JSONDecodeError, TypeError):
                    pass
            
            for point in points:
                # First, handle camera_index remapping if needed
                if point.camera_index is not None:
                    old_idx_str = str(point.camera_index)
                    if old_idx_str in old_to_new_index_map:
                        # Remap to new index
                        new_idx = int(old_to_new_index_map[old_idx_str])
                        point.camera_index = new_idx
                        point_update_count += 1
                    else:
                        # Camera at this index was removed - try to find matching URL
                        # If we can't find it, set to None
                        if point.camera_index < len(old_camera_urls):
                            old_url = old_camera_urls[point.camera_index]
                            try:
                                new_idx = camera_urls.index(old_url)
                                point.camera_index = new_idx
                                point_update_count += 1
                            except ValueError:
                                # URL not found in new list, set to None
                                point.camera_index = None
                                point.stream_timestamp = None
                                point_update_count += 1
                        else:
                            # Index was out of bounds, set to None
                            point.camera_index = None
                            point.stream_timestamp = None
                            point_update_count += 1
                
                # Recompute stream_timestamp for all points that have a camera_index and stamp
                # This ensures timestamps are recalculated based on current stream start times
                if point.camera_index is not None and point.stamp:
                    camera_idx_str = str(point.camera_index)
                    if camera_idx_str in stream_starts:
                        stream_start_time = stream_starts[camera_idx_str]
                        new_timestamp = calculate_stream_timestamp(point.stamp, stream_start_time)
                        if new_timestamp is not None:
                            point.stream_timestamp = new_timestamp
                            point_update_count += 1
    
    # Propagate field name change to all matches that reference this field
    name_update_count = 0
    if old_field_name != new_field_name:
        for match in matches_to_update:
            match.field = new_field_name
            name_update_count += 1
    
    # Generate success message
    update_messages = []
    if name_update_count > 0:
        update_messages.append(f"Updated {name_update_count} match(es) to use the new field name")
    if camera_urls_changed:
        if camera_update_count > 0:
            update_messages.append(f"Updated camera stream data for {camera_update_count} match(es)")
        if point_update_count > 0:
            update_messages.append(f"Updated camera indices for {point_update_count} point(s)")
    
    if update_messages:
        flash(f'Field updated successfully! {" ".join(update_messages)}.', 'success')
    else:
        flash('Field updated successfully!', 'success')
    
    db.session.commit()
    return redirect(f'/{tournament_url}/setup')


@bp.route('/<tournament_url>/delete-field', methods=['POST'])
@login_required
def delete_field(tournament_url):
    """Delete field."""
    if is_not_TO(tournament_url):
        return redirect(f'/{tournament_url}')
    
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
    if is_not_TO(tournament_url):
        return redirect(f'/{tournament_url}')
    
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
    if is_not_TO(tournament_url):
        return redirect(f'/{tournament_url}')
    
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
    if is_not_TO(tournament_url):
        return redirect(f'/{tournament_url}')

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
    if is_not_TO(tournament_url):
        return redirect(f'/{tournament_url}')
    
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
    if is_not_TO(tournament_url):
        return redirect(f'/{tournament_url}')
    
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
    if is_not_TO(tournament_url):
        return redirect(f'/{tournament_url}')
    
    match_id = request.form.get('match_id')
    if not match_id:
        flash('Match ID is required', 'error')
        return redirect(f'/{tournament_url}/setup')
    
    match = Match.query.get_or_404(match_id)
    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()
    
    # Check if BREAK or JOIN is selected from the Match Type dropdown (renamed from 'dynamic')
    match_type_value = request.form.get('dynamic', '')
    
    if match_type_value == 'BREAK':
        schedule_type = 'BREAK'
        set_type = match.set_type  # Keep existing set_type
    elif match_type_value == 'JOIN':
        schedule_type = 'JOIN'
        set_type = match.set_type  # Keep existing set_type
    else:
        schedule_type = 'DYNAMIC' if match_type_value == 'true' else 'STATIC'
        set_type = request.form.get('match_type', match.set_type)
    
    # BREAK and JOIN matches don't have teams/refs
    if schedule_type in ('BREAK', 'JOIN'):
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
    match.schedule_type = schedule_type
    match.set_type = set_type
    match.ribbon = request.form.get('ribbon', '') == 'on'  # Checkbox value
    
    # BREAK and JOIN don't have nsets
    if schedule_type not in ('BREAK', 'JOIN'):
        match.nsets = int(request.form.get('nsets', 3))
    else:
        match.nsets = None
    
    # JOIN has zero length, BREAK can have length
    if schedule_type == 'JOIN':
        match.nominal_length = 0
    elif schedule_type == 'BREAK':
        match.nominal_length = int(request.form.get('length', match.nominal_length or 60))
    else:
        match.nominal_length = int(request.form.get('length', match.nominal_length or 60))
    
    match.refs_initial = refs_initial
    
    # For dynamic matches, set previous_match from form and compute start time from it
    # For static matches, ensure previous_match is cleared and use provided start_time
    if schedule_type != 'STATIC':
        # Get previous_match from form
        prev_match_id = request.form.get('previous_match', '')
        if prev_match_id:
            # Update doubly linked list: insert this match after prev_match
            update_match_previous_link(match, prev_match_id, tournament_url, is_new=False)
        else:
            # Clear previous_match and update old previous's next_match if needed
            old_prev = match.previous_match
            match.previous_match = None
            if old_prev:
                old_prev_m = Match.query.filter_by(uuid=old_prev, event=tournament_url).first()
                if old_prev_m and old_prev_m.next_match == match.uuid:
                    old_prev_m.next_match = None
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
    if is_not_TO(tournament_url):
        return redirect(f'/{tournament_url}')
    
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
    
    # Recompute all match times after tag updates (may affect dependencies)
    if updated_count > 0:
        try:
            recompute_all_match_times(tournament_url)
            db.session.commit()
        except Exception as e:
            print(f"Error recomputing match times after tag update: {e}")
    
    if updated_count > 0:
        flash(f'Successfully updated {updated_count} match(es) with tag conversions', 'success')
    else:
        flash('No matches were updated. No matches contain the selected tags.', 'info')
    
    return redirect(f'/{tournament_url}/setup')


@bp.route('/<tournament_url>/recompute-schedule', methods=['POST'])
@login_required
def recompute_schedule(tournament_url):
    """Recompute all match times for troubleshooting."""
    if is_not_TO(tournament_url):
        return redirect(f'/{tournament_url}')
    
    try:
        recompute_all_match_times(tournament_url)
        db.session.commit()
        flash('Schedule recomputed successfully', 'success')
    except Exception as e:
        flash(f'Error recomputing schedule: {str(e)}', 'error')
        print(f"Error recomputing schedule: {e}")
    
    return redirect(f'/{tournament_url}/setup')


@bp.route('/<tournament_url>/update-all-references', methods=['POST'])
@login_required
def update_all_references(tournament_url):
    """Update all match references (winner/loser) for troubleshooting."""
    if is_not_TO(tournament_url):
        return redirect(f'/{tournament_url}')
    
    from app.utils.dependencies import apply_match_dependencies
    
    # Get all completed matches
    completed_matches = Match.query.filter_by(
        event=tournament_url,
        status='COMPLETED'
    ).all()
    
    updated_count = 0
    for match in completed_matches:
        if match.match_winner in ('TEAM1', 'TEAM2'):
            try:
                apply_match_dependencies(tournament_url, match)
                updated_count += 1
            except Exception as e:
                print(f"Error updating references for match {match.name}: {e}")
    
    if updated_count > 0:
        flash(f'Updated references for {updated_count} completed matches', 'success')
    else:
        flash('No references were updated', 'info')
    
    return redirect(f'/{tournament_url}/setup')


@bp.route('/<tournament_url>/push-back-matches', methods=['POST'])
@login_required
def push_back_matches(tournament_url):
    """Push all non-started matches backwards by a specified amount of time (in minutes)."""
    if is_not_TO(tournament_url):
        return redirect(f'/{tournament_url}')
    
    try:
        minutes = int(request.form.get('minutes', 0))
        if minutes <= 0:
            flash('Please specify a positive number of minutes', 'error')
            return redirect(f'/{tournament_url}/setup')
    except (ValueError, TypeError):
        flash('Invalid number of minutes', 'error')
        return redirect(f'/{tournament_url}/setup')
    
    # Get all non-started matches (status != 'IN_PROGRESS' and status != 'COMPLETED')
    non_started_matches = Match.query.filter_by(event=tournament_url).filter(
        ~Match.status.in_(['IN_PROGRESS', 'COMPLETED'])
    ).all()
    
    updated_count = 0
    for match in non_started_matches:
        # Push back nominal_start_time if it exists
        if match.nominal_start_time:
            match.nominal_start_time = match.nominal_start_time + timedelta(minutes=minutes)
            updated_count += 1
        
        # Also push back confirmed_start_time if it exists (even for time_finalized matches)
        if match.confirmed_start_time:
            match.confirmed_start_time = match.confirmed_start_time + timedelta(minutes=minutes)
    
    db.session.commit()
    
    if updated_count > 0:
        flash(f'Pushed back {updated_count} non-started match(es) by {minutes} minute(s)', 'success')
    else:
        flash('No matches were updated. All matches have already started or been completed.', 'info')
    
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


@bp.route('/<tournament_url>/delete', methods=['POST'])
@login_required
def delete_tournament(tournament_url):
    """Delete a tournament and all related data."""
    if is_not_TO(tournament_url):
        return redirect(f'/{tournament_url}')
    
    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()
    
    # Verify confirmation URL slug
    confirm_url = request.form.get('confirm_url', '').strip()
    if confirm_url != tournament_url:
        flash('Confirmation URL does not match. Tournament not deleted.', 'error')
        return redirect(f'/{tournament_url}')
    
    # Import all necessary models
    from models import (
        Point, MatchNote, TeamRecord, PlayerRecord, Match,
        HeadRef, TeamInvitation, PlayerRegistration, TeamRegistration,
        Field, Tag, SideComp, SideCompResult
    )
    
    # Delete in order to respect foreign key constraints
    
    # 1. Delete SideCompResult (depends on SideComp)
    side_comps = SideComp.query.filter_by(event=tournament_url).all()
    side_comp_ids = [sc.id for sc in side_comps]
    if side_comp_ids:
        SideCompResult.query.filter(SideCompResult.comp.in_(side_comp_ids)).delete(synchronize_session=False)
    
    # 2. Delete SideComp (depends on Tournament)
    SideComp.query.filter_by(event=tournament_url).delete(synchronize_session=False)
    
    # 3. Get all matches for this tournament
    matches = Match.query.filter_by(event=tournament_url).all()
    match_uuids = [m.uuid for m in matches]
    
    # 4. Delete Point (depends on Match)
    if match_uuids:
        Point.query.filter(Point.match.in_(match_uuids)).delete(synchronize_session=False)
    
    # 5. Delete MatchNote (depends on Match)
    if match_uuids:
        MatchNote.query.filter(MatchNote.match.in_(match_uuids)).delete(synchronize_session=False)
    
    # 6. Delete TeamRecord (depends on Match and Tournament)
    if match_uuids:
        TeamRecord.query.filter(
            TeamRecord.event == tournament_url
        ).filter(
            TeamRecord.match.in_(match_uuids)
        ).delete(synchronize_session=False)
    # Also delete TeamRecords that don't have a match
    TeamRecord.query.filter_by(event=tournament_url, match=None).delete(synchronize_session=False)
    
    # 7. Delete PlayerRecord (depends on Match and Tournament)
    if match_uuids:
        PlayerRecord.query.filter(
            PlayerRecord.event == tournament_url
        ).filter(
            PlayerRecord.match.in_(match_uuids)
        ).delete(synchronize_session=False)
    # Also delete PlayerRecords that don't have a match
    PlayerRecord.query.filter_by(event=tournament_url, match=None).delete(synchronize_session=False)
    
    # 8. Delete Match (depends on Tournament)
    Match.query.filter_by(event=tournament_url).delete(synchronize_session=False)
    
    # 9. Delete HeadRef (depends on Tournament)
    HeadRef.query.filter_by(event=tournament_url).delete(synchronize_session=False)
    
    # 10. Delete TeamInvitation (depends on Tournament)
    TeamInvitation.query.filter_by(event=tournament_url).delete(synchronize_session=False)
    
    # 11. Delete PlayerRegistration (depends on Tournament)
    PlayerRegistration.query.filter_by(event=tournament_url).delete(synchronize_session=False)
    
    # 12. Delete TeamRegistration (depends on Tournament)
    TeamRegistration.query.filter_by(event=tournament_url).delete(synchronize_session=False)
    
    # 13. Delete Field (depends on Tournament)
    Field.query.filter_by(event=tournament_url).delete(synchronize_session=False)
    
    # 14. Delete Tag (depends on Tournament)
    Tag.query.filter_by(event=tournament_url).delete(synchronize_session=False)
    
    # 15. Delete TO (depends on Tournament)
    TO.query.filter_by(event=tournament_url).delete(synchronize_session=False)
    
    # 16. Delete Tournament (last)
    db.session.delete(tournament)
    
    db.session.commit()
    
    flash(f'Tournament "{tournament.name}" has been permanently deleted.', 'success')
    return redirect('/')


@bp.route('/<tournament_url>/add-to', methods=['POST'])
@login_required
def add_to(tournament_url):
    """Add a TO to the tournament."""
    
    if is_not_TO(tournament_url):
        return redirect(f'/{tournament_url}')
    
    user_id = request.form.get('user_id', '').strip()
    user_type = request.form.get('user_type', '').strip().lower()
    
    if not user_id or user_type not in ['player', 'team']:
        flash('Invalid user ID or type', 'error')
        return redirect(f'/{tournament_url}/settings')
    
    # Verify the user exists
    from models import Player, Team
    if user_type == 'player':
        user = Player.query.get(user_id)
        if not user:
            flash(f'Player with ID "{user_id}" not found', 'error')
            return redirect(f'/{tournament_url}/settings')
    else:  # team
        user = Team.query.get(user_id)
        if not user:
            flash(f'Team with ID "{user_id}" not found', 'error')
            return redirect(f'/{tournament_url}/settings')
    
    # Check if TO already exists
    existing_to = TO.query.filter_by(
        user_id=user_id,
        user_type=user_type,
        event=tournament_url
    ).first()
    
    if existing_to:
        flash(f'This user is already a TO for this tournament', 'error')
        return redirect(f'/{tournament_url}/settings')
    
    # Create new TO entry
    new_to = TO(
        user_id=user_id,
        user_type=user_type,
        event=tournament_url
    )
    db.session.add(new_to)
    db.session.commit()
    
    user_name = user.name if user else user_id
    flash(f'Successfully added {user_name} as a TO', 'success')
    return redirect(f'/{tournament_url}/settings')


@bp.route('/<tournament_url>/remove-to', methods=['POST'])
@login_required
def remove_to(tournament_url):
    """Remove a TO from the tournament."""

    if is_not_TO(tournament_url):
        return redirect(f'/{tournament_url}')
    
    to_id = request.form.get('to_id')
    if not to_id:
        flash('TO ID is required', 'error')
        return redirect(f'/{tournament_url}/settings')
    
    # Get the TO entry to remove
    to_to_remove = TO.query.get_or_404(to_id)
    
    # Verify it's for this tournament
    if to_to_remove.event != tournament_url:
        flash('Invalid TO entry', 'error')
        return redirect(f'/{tournament_url}/settings')
    
    # Prevent removing yourself (optional - you might want to allow this)
    if to_to_remove.user_id == current_user.id and to_to_remove.user_type == current_user.__class__.__name__.lower():
        flash('You cannot remove yourself as a TO', 'error')
        return redirect(f'/{tournament_url}/settings')
    
    # Get user info for flash message
    from models import Player, Team
    if to_to_remove.user_type == 'player':
        user = Player.query.get(to_to_remove.user_id)
    else:
        user = Team.query.get(to_to_remove.user_id)
    user_name = user.name if user else to_to_remove.user_id
    
    # Delete the TO entry
    db.session.delete(to_to_remove)
    db.session.commit()
    
    flash(f'Successfully removed {user_name} as a TO', 'success')
    return redirect(f'/{tournament_url}/settings')

