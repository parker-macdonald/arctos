"""
Authentication routes (login, register, logout).
"""
from flask import Blueprint, render_template, request, redirect, flash, jsonify, url_for, session, current_app
from flask_login import login_user, logout_user, login_required, current_user
from models import Player, Team, db, Tournament, TO
from datetime import datetime
from app.utils.helpers import is_valid_url_username
from authlib.integrations.flask_client import OAuth
import re

bp = Blueprint('auth', __name__)

# Initialize OAuth (will be configured in app factory)
oauth = OAuth()


@bp.route('/login', methods=['GET', 'POST'])
def login():
    """User login page."""
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
            return redirect('/')
        else:
            flash('Invalid username or password', 'error')
    
    user_type = request.args.get('type', 'player')
    return render_template('login.html', user_type=user_type)


@bp.route('/register', methods=['GET', 'POST'])
def register():
    """User registration page."""
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        name = request.form['name']
        user_type = request.form.get('user_type', 'player')
        
        # Validate username is URL-safe
        if not is_valid_url_username(username):
            flash('Username must be URL-safe: only letters, numbers, hyphens, and underscores. Cannot start or end with hyphen or underscore.', 'error')
            return render_template('register.html', user_type=user_type)
        
        # Check if username exists in either Player or Team (prevent conflicts)
        existing_player = Player.query.filter_by(id=username).first()
        existing_team = Team.query.filter_by(id=username).first()
        
        if existing_player or existing_team:
            flash('Username already exists', 'error')
            return render_template('register.html', user_type=user_type)
        
        if user_type == 'player':
            user = Player(id=username, name=name)
            user.set_password(password)
        else:
            user = Team(id=username, name=name)
            user.set_password(password)
        
        db.session.add(user)
        db.session.commit()
        
        login_user(user)
        flash('Account created successfully!', 'success')
        return redirect('/')
    
    user_type = request.args.get('type', 'player')
    return render_template('register.html', user_type=user_type)


@bp.route('/check-username', methods=['GET'])
def check_username():
    """Check if a username is available (not taken by any player or team)."""
    username = request.args.get('username', '')
    
    if not username:
        return jsonify({'available': False, 'message': 'Username is required'})
    
    # Check if username is valid format
    if not is_valid_url_username(username):
        return jsonify({
            'available': False, 
            'message': 'Username must be URL-safe: only letters, numbers, hyphens, and underscores. Cannot start or end with hyphen or underscore.'
        })
    
    # Check if username exists in either Player or Team
    existing_player = Player.query.filter_by(id=username).first()
    existing_team = Team.query.filter_by(id=username).first()
    
    if existing_player or existing_team:
        return jsonify({'available': False, 'message': 'Username already exists'})
    
    return jsonify({'available': True, 'message': 'Username is available'})


@bp.route('/logout')
@login_required
def logout():
    """User logout."""
    logout_user()
    flash('You have been logged out', 'info')
    return redirect('/')


@bp.route('/auth/google/login')
def google_login():
    """Initiate Google OAuth login."""
    user_type = request.args.get('type', 'player')
    
    # Store user_type in session for callback
    session['oauth_user_type'] = user_type
    
    # Check if Google OAuth is configured
    if not current_app.config.get('GOOGLE_CLIENT_ID') or not current_app.config.get('GOOGLE_CLIENT_SECRET'):
        flash('Google sign-in is not configured. Please contact the administrator.', 'error')
        return redirect(url_for('auth.login', type=user_type))
    
    # Get the redirect URI
    redirect_uri = url_for('auth.google_callback', _external=True)
    
    # Get OAuth client
    google = oauth.google
    
    return google.authorize_redirect(redirect_uri)


@bp.route('/auth/google/callback')
def google_callback():
    """Handle Google OAuth callback."""
    user_type = session.get('oauth_user_type', 'player')
    
    try:
        # Get OAuth client
        google = oauth.google
        token = google.authorize_access_token()
        
        # Get user info from Google (use absolute endpoint from provider metadata)
        userinfo_endpoint = getattr(google, "server_metadata", {}).get("userinfo_endpoint")
        if not userinfo_endpoint:
            # Fallback to OpenID config fetch if not already loaded
            try:
                google.load_server_metadata()
                userinfo_endpoint = google.server_metadata.get("userinfo_endpoint")
            except Exception:
                userinfo_endpoint = None
        if not userinfo_endpoint:
            raise RuntimeError('Google userinfo endpoint not found in provider metadata')
        resp = google.get(userinfo_endpoint)
        user_info = resp.json()
        
        google_id = user_info.get('sub')
        email = user_info.get('email', '')
        name = user_info.get('name', email.split('@')[0] if email else 'User')
        
        if not google_id:
            flash('Failed to authenticate with Google', 'error')
            return redirect(url_for('auth.login', type=user_type))
        
        # Check if user already exists with this Google ID
        if user_type == 'player':
            user = Player.query.filter_by(google_id=google_id).first()
        else:
            user = Team.query.filter_by(google_id=google_id).first()
        
        if user:
            # Existing user, log them in
            login_user(user)
            flash('Successfully logged in with Google!', 'success')
            return redirect('/')
        
        # New user - store Google info in session and redirect to username selection
        session['google_oauth_data'] = {
            'google_id': google_id,
            'email': email,
            'name': name,
            'user_type': user_type
        }
        return redirect(url_for('auth.google_complete_profile'))
        
    except Exception as e:
        flash(f'Error during Google authentication: {str(e)}', 'error')
        return redirect(url_for('auth.login', type=user_type))


@bp.route('/auth/google/complete-profile', methods=['GET', 'POST'])
def google_complete_profile():
    """Complete profile setup for new Google OAuth users."""
    oauth_data = session.get('google_oauth_data')
    
    if not oauth_data:
        flash('Session expired. Please try signing in again.', 'error')
        return redirect(url_for('auth.login', type='player'))
    
    user_type = oauth_data.get('user_type', 'player')
    email = oauth_data.get('email', '')
    suggested_name = oauth_data.get('name', email.split('@')[0] if email else 'User')
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        display_name = request.form.get('display_name', '').strip()
        
        # Validate username
        if not username:
            flash('Username is required', 'error')
            return render_template('google_complete_profile.html', 
                                 user_type=user_type, 
                                 suggested_name=suggested_name,
                                 email=email)
        
        if not is_valid_url_username(username):
            flash('Username must be URL-safe: only letters, numbers, hyphens, and underscores. Cannot start or end with hyphen or underscore.', 'error')
            return render_template('google_complete_profile.html', 
                                 user_type=user_type, 
                                 suggested_name=suggested_name,
                                 email=email)
        
        # Check if username exists
        existing_player = Player.query.filter_by(id=username).first()
        existing_team = Team.query.filter_by(id=username).first()
        
        if existing_player or existing_team:
            flash('Username already exists. Please choose a different one.', 'error')
            return render_template('google_complete_profile.html', 
                                 user_type=user_type, 
                                 suggested_name=suggested_name,
                                 email=email)
        
        # Validate display name
        if not display_name:
            flash('Display name is required', 'error')
            return render_template('google_complete_profile.html', 
                                 user_type=user_type, 
                                 suggested_name=suggested_name,
                                 email=email)
        
        # Create new user
        if user_type == 'player':
            user = Player(
                id=username,
                name=display_name,
                google_id=oauth_data['google_id'],
                email=email,
                profile_photo=None  # No profile photo from Google
            )
        else:
            user = Team(
                id=username,
                name=display_name,
                google_id=oauth_data['google_id'],
                email=email,
                profile_photo=None  # No profile photo from Google
            )
        
        db.session.add(user)
        db.session.commit()
        
        # Clear OAuth data from session
        session.pop('google_oauth_data', None)
        
        login_user(user)
        flash('Account created and logged in with Google!', 'success')
        return redirect('/')
    
    return render_template('google_complete_profile.html', 
                         user_type=user_type, 
                         suggested_name=suggested_name,
                         email=email)

