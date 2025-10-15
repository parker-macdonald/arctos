from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import uuid
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///tournament.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Import models first to get db instance
from models import db, init_db
db.init_app(app)
init_db(db)

# Import all models after db is initialized
from models import *

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    # Try to load as player first, then team
    user = Player.query.get(user_id)
    if user:
        return user
    return Team.query.get(user_id)

@app.route('/')
def index():
    # Get published tournaments
    published_tournaments = Tournament.query.filter_by(published=True).order_by(Tournament.start_date.desc()).all()
    
    # Get tournaments where current user is TO (if logged in)
    to_tournaments = []
    if current_user.is_authenticated:
        to_entries = TO.query.filter_by(user_id=current_user.id, user_type=current_user.__class__.__name__.lower()).all()
        tournament_urls = [entry.event for entry in to_entries]
        to_tournaments = Tournament.query.filter(Tournament.url.in_(tournament_urls)).order_by(Tournament.start_date.desc()).all()
    
    return render_template('index.html', tournaments=published_tournaments, to_tournaments=to_tournaments)


@app.route('/teams')
def teams():
    search = request.args.get('search', '')
    if search:
        teams = Team.query.filter(Team.name.contains(search) | Team.id.contains(search)).all()
    else:
        teams = Team.query.all()
    return render_template('teams.html', teams=teams)

@app.route('/players')
def players():
    search = request.args.get('search', '')
    if search:
        players = Player.query.filter(Player.name.contains(search) | Player.id.contains(search)).all()
    else:
        players = Player.query.all()
    return render_template('players.html', players=players)

@app.route('/players/<player_id>')
def player_profile(player_id):
    player = Player.query.get_or_404(player_id)
    # Get player's tournament registrations
    registrations = PlayerRegistration.query.filter_by(player=player_id).all()
    # Get player's injuries
    injuries = Injury.query.filter_by(player=player_id).order_by(Injury.stamp.desc()).all()
    return render_template('player_profile.html', player=player, registrations=registrations, injuries=injuries)

@app.route('/teams/<team_id>')
def team_profile(team_id):
    team = Team.query.get_or_404(team_id)
    # Get team's tournament registrations
    team_registrations = TeamRegistration.query.filter_by(team=team_id).all()
    # Get player registrations for this team
    player_registrations = PlayerRegistration.query.filter_by(team=team_id).all()
    # Get tournaments for date display
    tournaments = Tournament.query.all()
    
    # Get accepted players for each tournament (only if logged in as this team)
    tournament_players = {}
    if current_user.is_authenticated and current_user.id == team_id and current_user.__class__.__name__ == 'Team':
        for team_reg in team_registrations:
            accepted_players = PlayerRegistration.query.filter_by(
                event=team_reg.event,
                team=team_id,
                status='CONFIRMED'
            ).all()
            tournament_players[team_reg.event] = accepted_players
    
    return render_template('team_profile.html', team=team, team_registrations=team_registrations, player_registrations=player_registrations, tournaments=tournaments, tournament_players=tournament_players)

@app.route('/players/<player_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_player_profile(player_id):
    if current_user.id != player_id:
        flash('You can only edit your own profile', 'error')
        return redirect(url_for('player_profile', player_id=player_id))
    
    player = Player.query.get_or_404(player_id)
    
    if request.method == 'POST':
        player.name = request.form['name']
        player.phone = request.form.get('phone', '')
        player.location = request.form.get('location', '')
        player.bio = request.form.get('bio', '')
        db.session.commit()
        flash('Profile updated successfully!', 'success')
        return redirect(url_for('player_profile', player_id=player_id))
    
    return render_template('edit_player_profile.html', player=player)

@app.route('/teams/<team_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_team_profile(team_id):
    if current_user.id != team_id:
        flash('You can only edit your own team profile', 'error')
        return redirect(url_for('team_profile', team_id=team_id))
    
    team = Team.query.get_or_404(team_id)
    
    if request.method == 'POST':
        team.name = request.form['name']
        team.location = request.form.get('location', '')
        team.email = request.form.get('email', '')
        team.website = request.form.get('website', '')
        team.about = request.form.get('about', '')
        db.session.commit()
        flash('Team profile updated successfully!', 'success')
        return redirect(url_for('team_profile', team_id=team_id))
    
    return render_template('edit_team_profile.html', team=team)

@app.route('/players/<player_id>/upload-photo', methods=['POST'])
@login_required
def upload_player_photo(player_id):
    if current_user.id != player_id:
        flash('You can only upload photos for your own profile', 'error')
        return redirect(url_for('player_profile', player_id=player_id))
    
    if 'photo' not in request.files:
        flash('No photo selected', 'error')
        return redirect(url_for('edit_player_profile', player_id=player_id))
    
    file = request.files['photo']
    if file.filename == '':
        flash('No photo selected', 'error')
        return redirect(url_for('edit_player_profile', player_id=player_id))
    
    if file:
        # Simple file handling - in production, use proper file validation and storage
        filename = f"player_{player_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.jpg"
        file.save(f"static/uploads/{filename}")
        
        player = Player.query.get_or_404(player_id)
        player.profile_photo = f"uploads/{filename}"
        db.session.commit()
        
        flash('Profile photo updated successfully!', 'success')
    
    return redirect(url_for('edit_player_profile', player_id=player_id))

@app.route('/teams/<team_id>/upload-photo', methods=['POST'])
@login_required
def upload_team_photo(team_id):
    if current_user.id != team_id:
        flash('You can only upload photos for your own team profile', 'error')
        return redirect(url_for('team_profile', team_id=team_id))
    
    if 'photo' not in request.files:
        flash('No photo selected', 'error')
        return redirect(url_for('edit_team_profile', team_id=team_id))
    
    file = request.files['photo']
    if file.filename == '':
        flash('No photo selected', 'error')
        return redirect(url_for('edit_team_profile', team_id=team_id))
    
    if file:
        # Simple file handling - in production, use proper file validation and storage
        filename = f"team_{team_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.jpg"
        file.save(f"static/uploads/{filename}")
        
        team = Team.query.get_or_404(team_id)
        team.profile_photo = f"uploads/{filename}"
        db.session.commit()
        
        flash('Profile photo updated successfully!', 'success')
    
    return redirect(url_for('edit_team_profile', team_id=team_id))

@app.route('/players/<player_id>/delete', methods=['POST'])
@login_required
def delete_player_account(player_id):
    if current_user.id != player_id:
        flash('You can only delete your own account', 'error')
        return redirect(url_for('player_profile', player_id=player_id))
    
    player = Player.query.get_or_404(player_id)
    
    # Delete related data
    Registration.query.filter_by(player=player_id).delete()
    Injury.query.filter_by(player=player_id).delete()
    TeamInvitation.query.filter_by(player=player_id).delete()
    
    db.session.delete(player)
    db.session.commit()
    
    logout_user()
    flash('Your account has been deleted', 'info')
    return redirect(url_for('index'))

@app.route('/teams/<team_id>/delete', methods=['POST'])
@login_required
def delete_team_account(team_id):
    if current_user.id != team_id:
        flash('You can only delete your own team account', 'error')
        return redirect(url_for('team_profile', team_id=team_id))
    
    team = Team.query.get_or_404(team_id)
    
    # Delete related data
    Registration.query.filter_by(team=team_id).delete()
    TeamInvitation.query.filter_by(team=team_id).delete()
    
    db.session.delete(team)
    db.session.commit()
    
    logout_user()
    flash('Your team account has been deleted', 'info')
    return redirect(url_for('index'))

@app.route('/new-tournament')
@login_required
def new_tournament():
    return render_template('new_tournament.html')

@app.route('/create-tournament', methods=['POST'])
@login_required
def create_tournament():
    name = request.form['name']
    url = request.form['url']
    
    # Check if tournament URL already exists
    if Tournament.query.filter_by(url=url).first():
        flash('Tournament URL already exists', 'error')
        return redirect(url_for('new_tournament'))
    
    # Create tournament
    tournament = Tournament(
        url=url,
        name=name,
        start_date=datetime.utcnow(),  # Default to now, can be updated later
        end_date=None  # Can be set later
    )
    
    db.session.add(tournament)
    
    # Add current user as TO
    to_entry = TO(
        user_id=current_user.id,
        user_type=current_user.__class__.__name__.lower(),
        event=url
    )
    db.session.add(to_entry)
    
    db.session.commit()
    
    flash(f'Tournament "{name}" created successfully!', 'success')
    return redirect(url_for('tournament_home', tournament_url=url))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user_type = request.form.get('user_type', 'player')
        
        if user_type == 'player':
            user = Player.query.filter_by(id=username).first()
        else:
            user = Team.query.filter_by(id=username).first()
        
        if user and user.check_password(password):
            login_user(user)
            flash('Successfully logged in!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Invalid username or password', 'error')
    
    user_type = request.args.get('type', 'player')
    return render_template('login.html', user_type=user_type)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        name = request.form['name']
        user_type = request.form.get('user_type', 'player')
        
        if user_type == 'player':
            if Player.query.filter_by(id=username).first():
                flash('Username already exists', 'error')
                return render_template('register.html', user_type=user_type)
            
            user = Player(id=username, name=name)
            user.set_password(password)
        else:
            if Team.query.filter_by(id=username).first():
                flash('Username already exists', 'error')
                return render_template('register.html', user_type=user_type)
            
            user = Team(id=username, name=name)
            user.set_password(password)
        
        db.session.add(user)
        db.session.commit()
        
        login_user(user)
        flash('Account created successfully!', 'success')
        return redirect(url_for('index'))
    
    user_type = request.args.get('type', 'player')
    return render_template('register.html', user_type=user_type)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out', 'info')
    return redirect(url_for('index'))

@app.route('/<tournament_url>')
def tournament_home(tournament_url):
    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()
    
    # Check if tournament is published or user is TO
    if not tournament.published:
        if not current_user.is_authenticated:
            flash('This tournament is not yet published', 'error')
            return redirect(url_for('index'))
        
        # Check if user is TO for this tournament
        is_to = TO.query.filter_by(
            user_id=current_user.id, 
            user_type=current_user.__class__.__name__.lower(),
            event=tournament_url
        ).first()
        
        if not is_to:
            flash('This tournament is not yet published', 'error')
            return redirect(url_for('index'))
    
    # Get registered teams with player counts
    team_registrations = TeamRegistration.query.filter_by(
        event=tournament_url,
        status='CONFIRMED'
    ).all()
    
    # Get player counts for each team
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
    
    # Get unattached players with player objects
    unattached_players = []
    player_registrations = PlayerRegistration.query.filter_by(
        event=tournament_url,
        team=None,
        status='CONFIRMED'
    ).all()
    
    for player_reg in player_registrations:
        player = Player.query.get(player_reg.player)
        if player:
            unattached_players.append({
                'registration': player_reg,
                'player': player
            })
    
    # Get TO entries for access control
    to_entries = TO.query.filter_by(event=tournament_url).all()
    
    return render_template('tournament_home.html', tournament=tournament, teams_with_counts=teams_with_counts, unattached_players=unattached_players, to_entries=to_entries)

def check_tournament_access(tournament_url):
    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()
    
    # Check if tournament is published or user is TO
    if not tournament.published:
        if not current_user.is_authenticated:
            flash('This tournament is not yet published', 'error')
            return None
        
        # Check if user is TO for this tournament
        is_to = TO.query.filter_by(
            user_id=current_user.id, 
            user_type=current_user.__class__.__name__.lower(),
            event=tournament_url
        ).first()
        
        if not is_to:
            flash('This tournament is not yet published', 'error')
            return None
    
    return tournament

@app.route('/<tournament_url>/schedule')
def tournament_schedule(tournament_url):
    tournament = check_tournament_access(tournament_url)
    if not tournament:
        return redirect(url_for('index'))
    
    matches = Match.query.filter_by(event=tournament_url).order_by(Match.nominal_start_time).all()
    return render_template('tournament_schedule.html', tournament=tournament, matches=matches)

@app.route('/<tournament_url>/bracket')
def tournament_bracket(tournament_url):
    tournament = check_tournament_access(tournament_url)
    if not tournament:
        return redirect(url_for('index'))
    
    matches = Match.query.filter_by(event=tournament_url).order_by(Match.nominal_start_time).all()
    return render_template('tournament_bracket.html', tournament=tournament, matches=matches)

@app.route('/<tournament_url>/results')
def tournament_results(tournament_url):
    tournament = check_tournament_access(tournament_url)
    if not tournament:
        return redirect(url_for('index'))
    
    matches = Match.query.filter_by(event=tournament_url, status='COMPLETED').all()
    return render_template('tournament_results.html', tournament=tournament, matches=matches)

@app.route('/<tournament_url>/match')
def match_page(tournament_url):
    match_id = request.args.get('id')
    if not match_id:
        flash('Match ID required', 'error')
        return redirect(url_for('tournament_schedule', tournament_url=tournament_url))
    
    tournament = check_tournament_access(tournament_url)
    if not tournament:
        return redirect(url_for('index'))
    
    match = Match.query.filter_by(uuid=match_id, event=tournament_url).first_or_404()
    points = Point.query.filter_by(match=match_id).order_by(Point.stamp).all()
    
    return render_template('match_page.html', tournament=tournament, match=match, points=points)

@app.route('/<tournament_url>/settings')
@login_required
def tournament_settings(tournament_url):
    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()
    
    # Check if user is a TO for this tournament
    to_entry = TO.query.filter_by(
        user_id=current_user.id,
        user_type=current_user.__class__.__name__.lower(),
        event=tournament_url
    ).first()
    
    if not to_entry:
        flash('You do not have permission to access tournament settings', 'error')
        return redirect(url_for('tournament_home', tournament_url=tournament_url))
    
    return render_template('tournament_settings.html', tournament=tournament)

@app.route('/<tournament_url>/setup')
@login_required
def tournament_setup(tournament_url):
    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()
    
    # Check if user is a TO for this tournament
    to_entry = TO.query.filter_by(
        user_id=current_user.id,
        user_type=current_user.__class__.__name__.lower(),
        event=tournament_url
    ).first()
    
    if not to_entry:
        flash('You do not have permission to access tournament setup', 'error')
        return redirect(url_for('tournament_home', tournament_url=tournament_url))
    
    matches = Match.query.filter_by(event=tournament_url).order_by(Match.nominal_start_time).all()
    fields = Field.query.filter_by(event=tournament_url).all()
    return render_template('tournament_setup.html', tournament=tournament, matches=matches, fields=fields)

@app.route('/<tournament_url>/register')
def tournament_register(tournament_url):
    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()
    
    # Get only teams that are registered for this tournament
    team_registrations = TeamRegistration.query.filter_by(
        event=tournament_url,
        status='CONFIRMED'
    ).all()
    
    # Get team objects with their pseudonyms
    registered_teams = []
    for team_reg in team_registrations:
        team = Team.query.get(team_reg.team)
        if team:
            registered_teams.append({
                'team': team,
                'pseudonym': team_reg.pseudonym
            })
    
    return render_template('tournament_register.html', tournament=tournament, registered_teams=registered_teams)

@app.route('/<tournament_url>/update-settings', methods=['POST'])
def update_tournament_settings(tournament_url):
    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()
    
    # Update tournament settings
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
    tournament.published = 'published' in request.form
    tournament.registration_open = 'registration_open' in request.form
    
    if request.form.get('start_date'):
        tournament.start_date = datetime.strptime(request.form['start_date'], '%Y-%m-%d')
    
    if request.form.get('end_date'):
        tournament.end_date = datetime.strptime(request.form['end_date'], '%Y-%m-%d')
    else:
        tournament.end_date = None
    
    db.session.commit()
    flash('Tournament settings updated successfully!', 'success')
    return redirect(url_for('tournament_settings', tournament_url=tournament_url))

@app.route('/<tournament_url>/add-match', methods=['POST'])
def add_match(tournament_url):
    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()
    
    match = Match(
        name=request.form['match_name'],
        event=tournament_url,
        field=request.form.get('field', ''),
        team1_initial=request.form.get('team1', ''),
        team2_initial=request.form.get('team2', ''),
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
    return redirect(url_for('tournament_setup', tournament_url=tournament_url))

@app.route('/<tournament_url>/add-field', methods=['POST'])
def add_field(tournament_url):
    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()
    
    field = Field(
        event=tournament_url,
        name=request.form['field_name'],
        camera=request.form.get('camera', '')
    )
    
    db.session.add(field)
    db.session.commit()
    
    flash('Field added successfully!', 'success')
    return redirect(url_for('tournament_setup', tournament_url=tournament_url))

@app.route('/<tournament_url>/edit-match')
def edit_match(tournament_url):
    match_id = request.args.get('id')
    if not match_id:
        flash('Match ID required', 'error')
        return redirect(url_for('tournament_setup', tournament_url=tournament_url))
    
    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()
    match = Match.query.filter_by(uuid=match_id, event=tournament_url).first_or_404()
    fields = Field.query.filter_by(event=tournament_url).all()
    
    return render_template('edit_match.html', tournament=tournament, match=match, fields=fields)

@app.route('/<tournament_url>/update-match', methods=['POST'])
def update_match(tournament_url):
    match_id = request.form['match_id']
    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()
    match = Match.query.filter_by(uuid=match_id, event=tournament_url).first_or_404()
    
    # Update match fields
    match.name = request.form['match_name']
    match.field = request.form.get('field', '')
    match.team1_initial = request.form.get('team1', '')
    match.team2_initial = request.form.get('team2', '')
    match.type = request.form.get('match_type', 'SETS')
    match.nsets = int(request.form.get('nsets', 3))
    match.nominal_length = int(request.form.get('length', 60))
    match.dynamic = request.form.get('dynamic') == 'true'
    match.refs_initial = request.form.get('refs', '')
    
    if request.form.get('start_time'):
        match.nominal_start_time = datetime.strptime(request.form['start_time'], '%Y-%m-%dT%H:%M')
    
    db.session.commit()
    flash('Match updated successfully!', 'success')
    return redirect(url_for('tournament_setup', tournament_url=tournament_url))

@app.route('/<tournament_url>/register-team', methods=['POST'])
def register_team_for_tournament(tournament_url):
    if not current_user.is_authenticated or current_user.__class__.__name__ != 'Team':
        flash('Only teams can register for tournaments', 'error')
        return redirect(url_for('tournament_register', tournament_url=tournament_url))
    
    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()
    
    if not tournament.registration_open:
        flash('Registration is not open for this tournament', 'error')
        return redirect(url_for('tournament_register', tournament_url=tournament_url))
    
    # Check if team already registered
    existing_reg = TeamRegistration.query.filter_by(
        event=tournament_url,
        team=current_user.id
    ).first()
    
    if existing_reg:
        flash('Your team is already registered for this tournament', 'warning')
        return redirect(url_for('tournament_register', tournament_url=tournament_url))
    
    # Check team limit
    if tournament.n_max_teams:
        current_team_count = TeamRegistration.query.filter_by(
            event=tournament_url,
            status='CONFIRMED'
        ).count()
        
        if current_team_count >= tournament.n_max_teams:
            flash(f'Maximum number of teams ({tournament.n_max_teams}) already registered', 'error')
            return redirect(url_for('tournament_register', tournament_url=tournament_url))
    
    # Create team registration
    team_registration = TeamRegistration(
        event=tournament_url,
        team=current_user.id,
        pseudonym=request.form['pseudonym']
    )
    
    db.session.add(team_registration)
    db.session.commit()
    
    flash('Team registration successful!', 'success')
    return redirect(url_for('tournament_home', tournament_url=tournament_url))

@app.route('/<tournament_url>/register-player', methods=['POST'])
def register_player_for_tournament(tournament_url):
    if not current_user.is_authenticated or current_user.__class__.__name__ != 'Player':
        flash('Only players can register for tournaments', 'error')
        return redirect(url_for('tournament_register', tournament_url=tournament_url))
    
    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()
    
    if not tournament.registration_open:
        flash('Registration is not open for this tournament', 'error')
        return redirect(url_for('tournament_register', tournament_url=tournament_url))
    
    # Check if player has pending or accepted registration
    existing_reg = PlayerRegistration.query.filter_by(
        event=tournament_url,
        player=current_user.id
    ).filter(
        PlayerRegistration.status.in_(['PENDING_TEAM_APPROVAL', 'CONFIRMED'])
    ).first()
    
    if existing_reg:
        flash('You are already registered for this tournament', 'warning')
        return redirect(url_for('tournament_register', tournament_url=tournament_url))
    
    team_id = request.form.get('team', '') or None
    
    # Create player registration
    # Set status based on whether they're registering with a team or unattached
    status = 'CONFIRMED' if not team_id else 'PENDING_TEAM_APPROVAL'
    
    player_registration = PlayerRegistration(
        event=tournament_url,
        player=current_user.id,
        team=team_id,
        jersey_number=request.form.get('jersey_number', ''),
        jersey_name=request.form.get('jersey_name', ''),
        status=status
    )
    
    db.session.add(player_registration)
    
    # If registering under a team, create invitation
    if team_id:
        invitation = TeamInvitation(
            event=tournament_url,
            team=team_id,
            player=current_user.id
        )
        db.session.add(invitation)
    
    db.session.commit()
    
    if team_id:
        flash('Registration submitted! The team will need to approve your request.', 'success')
    else:
        flash('Player registration successful! You are now registered for the tournament.', 'success')
    
    return redirect(url_for('tournament_home', tournament_url=tournament_url))

@app.route('/<tournament_url>/deregister-team', methods=['POST'])
@login_required
def deregister_team_from_tournament(tournament_url):
    if current_user.__class__.__name__ != 'Team':
        flash('Only teams can deregister from tournaments', 'error')
        return redirect(url_for('tournament_home', tournament_url=tournament_url))
    
    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()
    
    if not tournament.registration_open:
        flash('Registration changes are locked. You can no longer deregister.', 'error')
        return redirect(url_for('tournament_home', tournament_url=tournament_url))
    
    # Find team registration
    team_registration = TeamRegistration.query.filter_by(
        event=tournament_url,
        team=current_user.id,
        status='CONFIRMED'
    ).first()
    
    if not team_registration:
        flash('You are not registered for this tournament', 'error')
        return redirect(url_for('tournament_home', tournament_url=tournament_url))
    
    # Cancel team registration
    team_registration.status = 'CANCELLED'
    
    # Cancel all player registrations for this team
    PlayerRegistration.query.filter_by(
        event=tournament_url,
        team=current_user.id
    ).update({'status': 'CANCELLED'})
    
    # Cancel all pending invitations for this team
    TeamInvitation.query.filter_by(
        event=tournament_url,
        team=current_user.id
    ).update({'status': 'DECLINED'})
    
    db.session.commit()
    flash('Team successfully deregistered from tournament', 'success')
    return redirect(url_for('tournament_home', tournament_url=tournament_url))

@app.route('/<tournament_url>/deregister-player', methods=['POST'])
@login_required
def deregister_player_from_tournament(tournament_url):
    if current_user.__class__.__name__ != 'Player':
        flash('Only players can deregister from tournaments', 'error')
        return redirect(url_for('tournament_home', tournament_url=tournament_url))
    
    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()
    
    if not tournament.registration_open:
        flash('Registration changes are locked. You can no longer deregister.', 'error')
        return redirect(url_for('tournament_home', tournament_url=tournament_url))
    
    # Find player registration
    player_registration = PlayerRegistration.query.filter_by(
        event=tournament_url,
        player=current_user.id
    ).filter(
        PlayerRegistration.status.in_(['PENDING_TEAM_APPROVAL', 'CONFIRMED'])
    ).first()
    
    if not player_registration:
        flash('You are not registered for this tournament', 'error')
        return redirect(url_for('tournament_home', tournament_url=tournament_url))
    
    # Cancel player registration
    player_registration.status = 'CANCELLED'
    
    # If they had a pending invitation, decline it
    if player_registration.team:
        invitation = TeamInvitation.query.filter_by(
            event=tournament_url,
            team=player_registration.team,
            player=current_user.id
        ).first()
        if invitation:
            invitation.status = 'DECLINED'
    
    db.session.commit()
    flash('Player successfully deregistered from tournament', 'success')
    return redirect(url_for('tournament_home', tournament_url=tournament_url))

@app.route('/<tournament_url>/manage')
@login_required
def tournament_manage(tournament_url):
    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()
    
    # Check if user is TO
    is_to = TO.query.filter_by(
        user_id=current_user.id, 
        user_type=current_user.__class__.__name__.lower(),
        event=tournament_url
    ).first()
    
    if not is_to:
        flash('Only tournament organizers can access this page', 'error')
        return redirect(url_for('tournament_home', tournament_url=tournament_url))
    
    # Get all team registrations with team objects (excluding cancelled)
    team_registrations = TeamRegistration.query.filter_by(event=tournament_url).filter(
        TeamRegistration.status != 'CANCELLED'
    ).all()
    teams_with_registrations = []
    for team_reg in team_registrations:
        team = Team.query.get(team_reg.team)
        if team:
            teams_with_registrations.append({
                'registration': team_reg,
                'team': team
            })
    
    # Get all player registrations with player objects (excluding cancelled)
    player_registrations = PlayerRegistration.query.filter_by(event=tournament_url).filter(
        PlayerRegistration.status != 'CANCELLED'
    ).all()
    
    # Get player objects for all registrations
    players_with_registrations = []
    for player_reg in player_registrations:
        player = Player.query.get(player_reg.player)
        team = Team.query.get(player_reg.team) if player_reg.team else None
        if player:
            players_with_registrations.append({
                'registration': player_reg,
                'player': player,
                'team': team
            })
    
    return render_template('tournament_manage.html', 
                         tournament=tournament, 
                         team_registrations=teams_with_registrations,
                         players_with_registrations=players_with_registrations)

@app.route('/<tournament_url>/deregister-any-team', methods=['POST'])
@login_required
def deregister_any_team(tournament_url):
    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()
    
    # Check if user is TO
    is_to = TO.query.filter_by(
        user_id=current_user.id, 
        user_type=current_user.__class__.__name__.lower(),
        event=tournament_url
    ).first()
    
    if not is_to:
        flash('Only tournament organizers can perform this action', 'error')
        return redirect(url_for('tournament_home', tournament_url=tournament_url))
    
    team_id = request.form.get('team_id')
    if not team_id:
        flash('Team ID is required', 'error')
        return redirect(url_for('tournament_manage', tournament_url=tournament_url))
    
    # Cancel team registration
    team_registration = TeamRegistration.query.filter_by(
        event=tournament_url,
        team=team_id,
        status='CONFIRMED'
    ).first()
    
    if team_registration:
        team_registration.status = 'CANCELLED'
        
        # Cancel all player registrations for this team
        PlayerRegistration.query.filter_by(
            event=tournament_url,
            team=team_id
        ).update({'status': 'CANCELLED'})
        
        # Cancel all pending invitations for this team
        TeamInvitation.query.filter_by(
            event=tournament_url,
            team=team_id
        ).update({'status': 'DECLINED'})
        
        db.session.commit()
        flash('Team successfully deregistered', 'success')
    else:
        flash('Team not found or already deregistered', 'error')
    
    return redirect(url_for('tournament_manage', tournament_url=tournament_url))

@app.route('/<tournament_url>/deregister-any-player', methods=['POST'])
@login_required
def deregister_any_player(tournament_url):
    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()
    
    # Check if user is TO
    is_to = TO.query.filter_by(
        user_id=current_user.id, 
        user_type=current_user.__class__.__name__.lower(),
        event=tournament_url
    ).first()
    
    if not is_to:
        flash('Only tournament organizers can perform this action', 'error')
        return redirect(url_for('tournament_home', tournament_url=tournament_url))
    
    player_id = request.form.get('player_id')
    if not player_id:
        flash('Player ID is required', 'error')
        return redirect(url_for('tournament_manage', tournament_url=tournament_url))
    
    # Cancel player registration
    player_registration = PlayerRegistration.query.filter_by(
        event=tournament_url,
        player=player_id
    ).filter(
        PlayerRegistration.status.in_(['PENDING_TEAM_APPROVAL', 'CONFIRMED'])
    ).first()
    
    if player_registration:
        player_registration.status = 'CANCELLED'
        
        # If they had a pending invitation, decline it
        if player_registration.team:
            invitation = TeamInvitation.query.filter_by(
                event=tournament_url,
                team=player_registration.team,
                player=player_id
            ).first()
            if invitation:
                invitation.status = 'DECLINED'
        
        db.session.commit()
        flash('Player successfully deregistered', 'success')
    else:
        flash('Player not found or already deregistered', 'error')
    
    return redirect(url_for('tournament_manage', tournament_url=tournament_url))

@app.route('/<tournament_url>/invitations')
def tournament_invitations(tournament_url):
    if not current_user.is_authenticated or current_user.__class__.__name__ != 'Team':
        flash('Only teams can view invitations', 'error')
        return redirect(url_for('tournament_home', tournament_url=tournament_url))
    
    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()
    
    # Get team registration for this tournament
    team_registration = TeamRegistration.query.filter_by(
        event=tournament_url,
        team=current_user.id,
        status='CONFIRMED'
    ).first()
    
    if not team_registration:
        flash('You are not registered for this tournament', 'error')
        return redirect(url_for('tournament_home', tournament_url=tournament_url))
    
    # Get pending invitations for this team
    invitations = TeamInvitation.query.filter_by(
        event=tournament_url,
        team=current_user.id,
        status='PENDING'
    ).all()
    
    # Get current team size
    current_team_size = PlayerRegistration.query.filter_by(
        event=tournament_url,
        team=current_user.id,
        status='CONFIRMED'
    ).count()
    
    # Get player registrations for context
    player_registrations = PlayerRegistration.query.filter_by(
        event=tournament_url,
        team=current_user.id
    ).all()
    
    return render_template('tournament_invitations.html', 
                         tournament=tournament, 
                         invitations=invitations,
                         current_team_size=current_team_size,
                         player_registrations=player_registrations,
                         team=current_user,
                         team_registration=team_registration)

@app.route('/<tournament_url>/invitation/<int:invitation_id>/accept', methods=['POST'])
def accept_invitation(tournament_url, invitation_id):
    if not current_user.is_authenticated or current_user.__class__.__name__ != 'Team':
        flash('Only teams can accept invitations', 'error')
        return redirect(url_for('tournament_invitations', tournament_url=tournament_url))
    
    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()
    invitation = TeamInvitation.query.filter_by(
        id=invitation_id,
        event=tournament_url,
        team=current_user.id
    ).first_or_404()
    
    # Check team size limit
    current_team_size = PlayerRegistration.query.filter_by(
        event=tournament_url,
        team=current_user.id,
        status='CONFIRMED'
    ).count()
    
    if tournament.max_team_size_roster and current_team_size >= tournament.max_team_size_roster:
        flash('Team is at maximum capacity', 'error')
        return redirect(url_for('tournament_invitations', tournament_url=tournament_url))
    
    # Update invitation status
    invitation.status = 'ACCEPTED'
    
    # Update player registration status
    player_reg = PlayerRegistration.query.filter_by(
        event=tournament_url,
        player=invitation.player,
        team=current_user.id
    ).first()
    
    if player_reg:
        player_reg.status = 'CONFIRMED'
    
    db.session.commit()
    flash('Invitation accepted!', 'success')
    return redirect(url_for('tournament_invitations', tournament_url=tournament_url))

@app.route('/<tournament_url>/invitation/<int:invitation_id>/decline', methods=['POST'])
def decline_invitation(tournament_url, invitation_id):
    if not current_user.is_authenticated or current_user.__class__.__name__ != 'Team':
        flash('Only teams can decline invitations', 'error')
        return redirect(url_for('tournament_invitations', tournament_url=tournament_url))
    
    invitation = TeamInvitation.query.filter_by(
        id=invitation_id,
        event=tournament_url,
        team=current_user.id
    ).first_or_404()
    
    # Update invitation status
    invitation.status = 'DECLINED'
    
    # Update player registration status
    player_reg = PlayerRegistration.query.filter_by(
        event=tournament_url,
        player=invitation.player,
        team=current_user.id
    ).first()
    
    if player_reg:
        player_reg.status = 'REJECTED'
    
    db.session.commit()
    flash('Invitation declined', 'info')
    return redirect(url_for('tournament_invitations', tournament_url=tournament_url))

@app.route('/players/<player_id>/add-injury', methods=['GET', 'POST'])
@login_required
def add_injury(player_id):
    if current_user.id != player_id:
        flash('You can only add injuries to your own profile', 'error')
        return redirect(url_for('player_profile', player_id=player_id))
    
    if request.method == 'POST':
        message = request.form['message']
        show = 'show' in request.form
        active = 'active' in request.form
        
        # Parse the custom date
        injury_date_str = request.form['injury_date']
        injury_date = datetime.strptime(injury_date_str, '%Y-%m-%d').date()
        
        injury = Injury(
            player=player_id,
            message=message,
            show=show,
            active=active,
            stamp=datetime.combine(injury_date, datetime.min.time())
        )
        
        db.session.add(injury)
        db.session.commit()
        
        flash('Injury added successfully!', 'success')
        return redirect(url_for('player_profile', player_id=player_id))
    
    return render_template('add_injury.html', player_id=player_id)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
