"""
Authentication routes (login, register, logout).
"""
from flask import Blueprint, render_template, request, redirect, flash, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from models import Player, Team, db, Tournament, TO
from datetime import datetime
from app.utils.helpers import is_valid_url_username

bp = Blueprint('auth', __name__)


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

