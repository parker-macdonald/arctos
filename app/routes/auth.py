"""
Authentication routes (login, register, logout).
"""
from flask import Blueprint, render_template, request, redirect, flash
from flask_login import login_user, logout_user, login_required, current_user
from models import Player, Team, db, Tournament, TO
from datetime import datetime

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
        username = request.form['username'].lower()  # Force lowercase
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
        return redirect('/')
    
    user_type = request.args.get('type', 'player')
    return render_template('register.html', user_type=user_type)


@bp.route('/logout')
@login_required
def logout():
    """User logout."""
    logout_user()
    flash('You have been logged out', 'info')
    return redirect('/')

