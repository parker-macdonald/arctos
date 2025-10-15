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
    published_tournaments = Tournament.query.filter_by(published=True).order_by(Tournament.dates.desc()).all()
    
    # Get tournaments where current user is TO (if logged in)
    to_tournaments = []
    if current_user.is_authenticated:
        to_entries = TO.query.filter_by(user_id=current_user.id, user_type=current_user.__class__.__name__.lower()).all()
        tournament_urls = [entry.event for entry in to_entries]
        to_tournaments = Tournament.query.filter(Tournament.url.in_(tournament_urls)).order_by(Tournament.dates.desc()).all()
    
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
    registrations = Registration.query.filter_by(player=player_id).all()
    # Get player's injuries
    injuries = Injury.query.filter_by(player=player_id).order_by(Injury.stamp.desc()).all()
    return render_template('player_profile.html', player=player, registrations=registrations, injuries=injuries)

@app.route('/teams/<team_id>')
def team_profile(team_id):
    team = Team.query.get_or_404(team_id)
    # Get team's tournament registrations
    registrations = Registration.query.filter_by(team=team_id).all()
    # Get team members
    team_members = Registration.query.filter_by(team=team_id).join(Player).all()
    return render_template('team_profile.html', team=team, registrations=registrations, team_members=team_members)

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
    admin_password = request.form['admin_password']
    
    # Check if tournament URL already exists
    if Tournament.query.filter_by(url=url).first():
        flash('Tournament URL already exists', 'error')
        return redirect(url_for('new_tournament'))
    
    # Create tournament
    tournament = Tournament(
        url=url,
        name=name,
        dates=datetime.utcnow(),  # Default to now, can be updated later
        admin_password=generate_password_hash(admin_password)
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
    if not tournament.published and (not current_user.is_authenticated or current_user.id != tournament.url):
        flash('This tournament is not yet published', 'error')
        return redirect(url_for('index'))
    
    return render_template('tournament_home.html', tournament=tournament)

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
def tournament_settings(tournament_url):
    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()
    return render_template('tournament_settings.html', tournament=tournament)

@app.route('/<tournament_url>/setup')
def tournament_setup(tournament_url):
    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()
    matches = Match.query.filter_by(event=tournament_url).order_by(Match.nominal_start_time).all()
    fields = Field.query.filter_by(event=tournament_url).all()
    return render_template('tournament_setup.html', tournament=tournament, matches=matches, fields=fields)

@app.route('/<tournament_url>/register')
def tournament_register(tournament_url):
    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()
    teams = Team.query.all()
    return render_template('tournament_register.html', tournament=tournament, teams=teams)

@app.route('/<tournament_url>/update-settings', methods=['POST'])
def update_tournament_settings(tournament_url):
    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()
    
    # Update tournament settings
    tournament.name = request.form['name']
    tournament.location = request.form.get('location', '')
    tournament.num_fields = int(request.form.get('num_fields', 1))
    tournament.n_max_teams = int(request.form.get('n_max_teams', 0)) or None
    tournament.max_team_size = int(request.form.get('max_team_size', 0)) or None
    tournament.team_reg_fee = float(request.form.get('team_reg_fee', 0))
    tournament.player_reg_fee = float(request.form.get('player_reg_fee', 0))
    tournament.about = request.form.get('about', '')
    tournament.published = 'published' in request.form
    
    if request.form.get('dates'):
        tournament.dates = datetime.strptime(request.form['dates'], '%Y-%m-%d')
    
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

@app.route('/<tournament_url>/register', methods=['POST'])
def register_for_tournament(tournament_url):
    if not current_user.is_authenticated:
        flash('You must be logged in to register', 'error')
        return redirect(url_for('login'))
    
    tournament = Tournament.query.filter_by(url=tournament_url).first_or_404()
    
    # Check if already registered
    existing_reg = Registration.query.filter_by(
        event=tournament_url,
        player=current_user.id if current_user.__class__.__name__ == 'Player' else None,
        team=current_user.id if current_user.__class__.__name__ == 'Team' else None
    ).first()
    
    if existing_reg:
        flash('You are already registered for this tournament', 'warning')
        return redirect(url_for('tournament_register', tournament_url=tournament_url))
    
    if current_user.__class__.__name__ == 'Player':
        registration = Registration(
            event=tournament_url,
            player=current_user.id,
            jersey=request.form.get('jersey', ''),
            team=request.form.get('team', '') or None,
            status='SENT'
        )
    else:
        # Team registration
        registration = Registration(
            event=tournament_url,
            player=None,  # Will be filled when players join
            team=current_user.id,
            status='SENT'
        )
    
    db.session.add(registration)
    db.session.commit()
    
    flash('Registration successful!', 'success')
    return redirect(url_for('tournament_home', tournament_url=tournament_url))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
