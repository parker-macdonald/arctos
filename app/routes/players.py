"""
Player profile and management routes.
"""
from flask import Blueprint, render_template, request, redirect, flash, current_app
from flask_login import login_required, current_user, logout_user
from datetime import datetime
import os
from models import (
    Player, PlayerRegistration, Injury, MatchNote, Point, db
)
from app.utils.helpers import is_head_ref_any

bp = Blueprint('players', __name__)


@bp.route('/players/<player_id>')
def player_profile(player_id):
    """Display player profile."""
    player = Player.query.get_or_404(player_id)
    registrations = PlayerRegistration.query.filter_by(player=player_id).all()
    injuries = Injury.query.filter_by(player=player_id).order_by(Injury.stamp.desc()).all()
    
    is_head_ref_flag = is_head_ref_any(player_id)
    player_notes = []
    if current_user.is_authenticated and (current_user.id == player_id or is_head_ref_flag):
        try:
            player_notes = MatchNote.query.filter_by(player_id=player_id).order_by(MatchNote.created_at.desc()).all()
        except Exception:
            player_notes = []
    
    player_note_rows = []
    if player_notes:
        match_to_points = {}
        for note in player_notes:
            idx = '-'
            match_obj = getattr(note, 'match_obj', None)
            if match_obj and note.point_id:
                match_id = match_obj.uuid
                if match_id not in match_to_points:
                    pts = Point.query.filter_by(match=match_id).order_by(Point.stamp).all()
                    match_to_points[match_id] = [p.uuid for p in pts]
                order = match_to_points.get(match_id, [])
                if note.point_id in order:
                    idx = order.index(note.point_id) + 1
            player_note_rows.append({
                'created_at': note.created_at,
                'text': note.text,
                'match_obj': match_obj,
                'point_index': idx
            })
    return render_template('player_profile.html', player=player, registrations=registrations, 
                         injuries=injuries, player_notes=player_note_rows, is_head_ref=is_head_ref_flag)


@bp.route('/players/<player_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_player_profile(player_id):
    """Edit player profile."""
    if current_user.id != player_id:
        flash('You can only edit your own profile', 'error')
        return redirect('/players/' + player_id)
    
    player = Player.query.get_or_404(player_id)
    
    if request.method == 'POST':
        player.name = request.form['name']
        player.phone = request.form.get('phone', '')
        player.location = request.form.get('location', '')
        player.bio = request.form.get('bio', '')
        db.session.commit()
        flash('Profile updated successfully!', 'success')
        return redirect('/players/' + player_id)
    
    return render_template('edit_player_profile.html', player=player)


@bp.route('/players/<player_id>/upload-photo', methods=['POST'])
@login_required
def upload_player_photo(player_id):
    """Upload player profile photo."""
    if current_user.id != player_id:
        flash('You can only upload photos for your own profile', 'error')
        return redirect('/players/' + player_id)
    
    if 'photo' not in request.files:
        flash('No photo selected', 'error')
        return redirect(f'/players/{player_id}/edit')
    
    file = request.files['photo']
    if file.filename == '':
        flash('No photo selected', 'error')
        return redirect(f'/players/{player_id}/edit')
    
    file.seek(0, 2)
    file_size = file.tell()
    file.seek(0)
    
    if file_size > 10 * 1024 * 1024:
        flash('File too large. Maximum size is 10MB.', 'error')
        return redirect(f'/players/{player_id}/edit')
    
    if file:
        try:
            upload_dir = os.path.join(current_app.root_path, "../static", "uploads")
            os.makedirs(upload_dir, exist_ok=True)
            filename = f"player_{player_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.jpg"
            file_path = os.path.join(upload_dir, filename)
            file.save(file_path)
            
            player = Player.query.get_or_404(player_id)
            player.profile_photo = f"uploads/{filename}"
            db.session.commit()
            flash('Profile photo updated successfully!', 'success')
        except Exception as e:
            flash(f'Error uploading photo: {str(e)}', 'error')
            db.session.rollback()
    
    return redirect(f'/players/{player_id}/edit')


@bp.route('/players/<player_id>/delete', methods=['POST'])
@login_required
def delete_player_account(player_id):
    """Delete player account."""
    if current_user.id != player_id:
        flash('You can only delete your own account', 'error')
        return redirect('/players/' + player_id)
    
    from models import TeamInvitation
    player = Player.query.get_or_404(player_id)
    
    PlayerRegistration.query.filter_by(player=player_id).delete()
    Injury.query.filter_by(player=player_id).delete()
    TeamInvitation.query.filter_by(player=player_id).delete()
    
    db.session.delete(player)
    db.session.commit()
    
    logout_user()
    flash('Your account has been deleted', 'info')
    return redirect('/')


@bp.route('/players/<player_id>/add-injury', methods=['GET', 'POST'])
@login_required
def add_injury(player_id):
    """Add injury to player profile."""
    if current_user.id != player_id:
        flash('You can only add injuries to your own profile', 'error')
        return redirect('/players/' + player_id)
    
    if request.method == 'POST':
        injury = Injury(
            player=player_id,
            message=request.form['message'],
            show='show' in request.form,
            active='active' in request.form
        )
        
        custom_date = request.form.get('custom_date')
        if custom_date:
            try:
                injury.stamp = datetime.strptime(custom_date, '%Y-%m-%d')
            except ValueError:
                flash('Invalid date format. Please use YYYY-MM-DD.', 'error')
                return render_template('add_injury.html', player_id=player_id)
        
        db.session.add(injury)
        db.session.commit()
        flash('Injury added successfully!', 'success')
        return redirect('/players/' + player_id)
    
    return render_template('add_injury.html', player_id=player_id)


@bp.route('/players/<player_id>/edit-injury/<int:injury_id>', methods=['GET', 'POST'])
@login_required
def edit_injury(player_id, injury_id):
    """Edit injury."""
    if current_user.id != player_id:
        flash('You can only edit injuries on your own profile', 'error')
        return redirect('/players/' + player_id)
    
    injury = Injury.query.filter_by(id=injury_id, player=player_id).first_or_404()
    
    if request.method == 'POST':
        injury.message = request.form['message']
        injury.show = 'show' in request.form
        injury.active = 'active' in request.form
        
        custom_date = request.form.get('custom_date')
        if custom_date:
            try:
                injury.stamp = datetime.strptime(custom_date, '%Y-%m-%d')
            except ValueError:
                flash('Invalid date format. Please use YYYY-MM-DD.', 'error')
                return render_template('edit_injury.html', injury=injury, player_id=player_id)
        
        db.session.commit()
        flash('Injury updated successfully!', 'success')
        return redirect('/players/' + player_id)
    
    return render_template('edit_injury.html', injury=injury, player_id=player_id)


@bp.route('/players/<player_id>/delete-injury/<int:injury_id>', methods=['POST'])
@login_required
def delete_injury(player_id, injury_id):
    """Delete injury."""
    if current_user.id != player_id:
        flash('You can only delete injuries from your own profile', 'error')
        return redirect('/players/' + player_id)
    
    injury = Injury.query.filter_by(id=injury_id, player=player_id).first_or_404()
    db.session.delete(injury)
    db.session.commit()
    flash('Injury deleted successfully!', 'success')
    return redirect('/players/' + player_id)

