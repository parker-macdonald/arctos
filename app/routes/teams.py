"""
Team profile and management routes.
"""
from flask import Blueprint, render_template, request, redirect, flash, current_app, url_for
from flask_login import login_required, current_user, logout_user
from datetime import datetime
from sqlalchemy import or_
import os
from models import (
    Team, TeamRegistration, PlayerRegistration, Tournament, MatchNote, Match, Point, db
)
from app.utils.helpers import is_head_ref_any

bp = Blueprint('teams', __name__)


@bp.route('/teams/<team_id>')
def team_profile(team_id):
    """Display team profile."""
    team = Team.query.get_or_404(team_id)
    team_registrations = TeamRegistration.query.filter_by(team=team_id).all()
    player_registrations = PlayerRegistration.query.filter_by(team=team_id).all()
    tournaments = Tournament.query.all()
    
    tournament_players = {}
    if current_user.is_authenticated and current_user.id == team_id and current_user.__class__.__name__ == 'Team':
        from models import Player
        for team_reg in team_registrations:
            accepted_players = PlayerRegistration.query.filter_by(
                event=team_reg.event,
                team=team_id,
                status='CONFIRMED'
            ).all()
            # Include Player objects for profile photos
            players_with_data = []
            for player_reg in accepted_players:
                player = Player.query.get(player_reg.player)
                players_with_data.append({
                    'registration': player_reg,
                    'player': player
                })
            tournament_players[team_reg.event] = players_with_data
    
    is_head_ref_flag = is_head_ref_any(team_id)
    team_notes = []
    # Only show notes to the team themselves, not to head refs
    if current_user.is_authenticated and (current_user.id == team_id or is_head_ref_flag):
        try:
            candidate_notes = MatchNote.query.filter(or_(MatchNote.target=='team1', MatchNote.target=='team2')).order_by(MatchNote.created_at.desc()).all()
            match_to_points = {}
            for n in candidate_notes:
                m = Match.query.get(n.match)
                if not m:
                    continue
                if not ((n.target=='team1' and m.team1 == team_id) or (n.target=='team2' and m.team2 == team_id)):
                    continue
                idx = '-'
                if n.point_id:
                    mid = m.uuid
                    if mid not in match_to_points:
                        pts = Point.query.filter_by(match=mid).order_by(Point.stamp).all()
                        match_to_points[mid] = [p.uuid for p in pts]
                    order = match_to_points.get(mid, [])
                    if n.point_id in order:
                        idx = order.index(n.point_id) + 1
                team_notes.append({
                    'created_at': n.created_at,
                    'text': n.text,
                    'match_obj': m,
                    'point_index': idx
                })
        except Exception:
            team_notes = []
    return render_template('team_profile.html', team=team, team_registrations=team_registrations, 
                         player_registrations=player_registrations, tournaments=tournaments, 
                         tournament_players=tournament_players, team_notes=team_notes, is_head_ref=is_head_ref_flag)


@bp.route('/teams/<team_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_team_profile(team_id):
    """Edit team profile."""
    if current_user.id != team_id:
        flash('You can only edit your own team profile', 'error')
        return redirect('/teams/' + team_id)
    
    team = Team.query.get_or_404(team_id)
    
    if request.method == 'POST':
        team.name = request.form['name']
        team.location = request.form.get('location', '')
        team.email = request.form.get('email', '')
        team.website = request.form.get('website', '')
        team.about = request.form.get('about', '')
        db.session.commit()
        flash('Team profile updated successfully!', 'success')
        return redirect('/teams/' + team_id)
    
    return render_template('edit_team_profile.html', team=team)


@bp.route('/teams/<team_id>/upload-photo', methods=['POST'])
@login_required
def upload_team_photo(team_id):
    """Upload team profile photo."""
    if current_user.id != team_id:
        flash('You can only upload photos for your own team profile', 'error')
        return redirect('/teams/' + team_id)
    
    if 'photo' not in request.files:
        flash('No photo selected', 'error')
        return redirect(f'/teams/{team_id}/edit')
    
    file = request.files['photo']
    if file.filename == '':
        flash('No photo selected', 'error')
        return redirect(f'/teams/{team_id}/edit')
    
    file.seek(0, 2)
    file_size = file.tell()
    file.seek(0)
    
    if file_size > 10 * 1024 * 1024:
        flash('File too large. Maximum size is 10MB.', 'error')
        return redirect(f'/teams/{team_id}/edit')
    
    if file:
        try:
            upload_dir = os.path.join(current_app.root_path, "../static", "uploads")
            os.makedirs(upload_dir, exist_ok=True)
            filename = f"team_{team_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.{file.filename.split('.')[-1]}"
            file_path = os.path.join(upload_dir, filename)
            file.save(file_path)
            
            team = Team.query.get_or_404(team_id)
            team.profile_photo = f"uploads/{filename}"
            db.session.commit()
            flash('Profile photo updated successfully!', 'success')
        except Exception as e:
            flash(f'Error uploading photo: {str(e)}', 'error')
            db.session.rollback()
    
    return redirect(f'/teams/{team_id}/edit')


@bp.route('/teams/<team_id>/delete', methods=['POST'])
@login_required
def delete_team_account(team_id):
    """Delete team account."""
    if current_user.id != team_id:
        flash('You can only delete your own team account', 'error')
        return redirect('/teams/' + team_id)
    
    from models import TeamInvitation
    team = Team.query.get_or_404(team_id)
    
    PlayerRegistration.query.filter_by(team=team_id).delete()
    TeamInvitation.query.filter_by(team=team_id).delete()
    
    db.session.delete(team)
    db.session.commit()
    
    logout_user()
    flash('Your team account has been deleted', 'info')
    return redirect('/')

