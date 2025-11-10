"""
Match notes management routes.
"""
from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from datetime import timezone
from models import Match, MatchNote, Player, PlayerRegistration, Point, db
from app.filters import is_head_ref
from app.utils.helpers import can_head_ref_match

bp = Blueprint('notes', __name__)


@bp.route('/<tournament_url>/get-notes')
@login_required
def get_notes(tournament_url):
    """Get notes for a match."""
    match_id = request.args.get('match_id')
    
    if not match_id:
        return jsonify({'success': False, 'error': 'Match ID required'})
    
    match = Match.query.get(match_id)
    if not match or match.event != tournament_url:
        return jsonify({'success': False, 'error': 'Match not found'})
    
    if not can_head_ref_match(tournament_url, current_user.id, match=match):
        return jsonify({'success': False, 'error': 'Not authorized'})
    
    point_id = request.args.get('point_id')
    
    if point_id:
        notes = MatchNote.query.filter_by(match=match_id).filter(
            (MatchNote.point_id == point_id) | (MatchNote.point_id.is_(None))
        ).order_by(MatchNote.created_at.desc()).all()
    else:
        notes = MatchNote.query.filter_by(match=match_id, point_id=None).order_by(MatchNote.created_at.desc()).all()
    
    notes_data = []
    for note in notes:
        player_name = None
        player_display = None
        if note.player_id:
            player = Player.query.get(note.player_id)
            if player:
                player_name = player.name
                reg = PlayerRegistration.query.filter_by(event=tournament_url, player=player.id).first()
                if reg:
                    if getattr(reg, 'jersey_name', None) and getattr(reg, 'jersey_number', None):
                        player_display = f"{reg.jersey_name} #{reg.jersey_number}"
                    elif getattr(reg, 'jersey_name', None):
                        player_display = reg.jersey_name
                    elif getattr(reg, 'jersey_number', None):
                        player_display = f"#{reg.jersey_number}"
                if not player_display:
                    player_display = player.name
        created_ts = note.created_at
        if created_ts and created_ts.tzinfo is None:
            created_ts = created_ts.replace(tzinfo=timezone.utc)
        if created_ts:
            created_ts = created_ts.replace(microsecond=0)
        # Determine team_id if target is TEAM1 or TEAM2
        team_id = None
        if note.target in ['TEAM1', 'team1']:
            team_id = match.team1
        elif note.target in ['TEAM2', 'team2']:
            team_id = match.team2
        
        notes_data.append({
            'uuid': note.uuid,
            'text': note.text,
            'target': note.target,
            'created_by': note.created_by,
            'created_at': created_ts.isoformat() if created_ts else None,
            'player_id': note.player_id,
            'player_name': player_name,
            'player_display': player_display,
            'team_id': team_id
        })
    
    return jsonify({'success': True, 'notes': notes_data})


@bp.route('/<tournament_url>/add-note', methods=['POST'])
@login_required
def add_note(tournament_url):
    """Add a note to a match."""
    match_id = request.json.get('match_id')
    text = request.json.get('text')
    target = request.json.get('target', 'MATCH')
    player_id = request.json.get('player_id')
    
    if not match_id or not text:
        return jsonify({'success': False, 'error': 'Match ID and text required'})
    
    match = Match.query.get(match_id)
    if not match or match.event != tournament_url:
        return jsonify({'success': False, 'error': 'Match not found'})
    
    if not can_head_ref_match(tournament_url, current_user.id, match=match):
        return jsonify({'success': False, 'error': 'Not authorized'})
    
    note = MatchNote(
        match=match_id,
        text=text,
        target=target,
        created_by=current_user.id,
        player_id=player_id if player_id else None
    )
    db.session.add(note)
    db.session.commit()
    
    player_name = None
    player_display = None
    if note.player_id:
        player = Player.query.get(note.player_id)
        if player:
            player_name = player.name
            reg = PlayerRegistration.query.filter_by(event=tournament_url, player=player.id).first()
            if reg:
                if getattr(reg, 'jersey_name', None) and getattr(reg, 'jersey_number', None):
                    player_display = f"{reg.jersey_name} #{reg.jersey_number}"
                elif getattr(reg, 'jersey_name', None):
                    player_display = reg.jersey_name
                elif getattr(reg, 'jersey_number', None):
                    player_display = f"#{reg.jersey_number}"
            if not player_display:
                player_display = player.name
    
    created_ts = note.created_at
    if created_ts and created_ts.tzinfo is None:
        created_ts = created_ts.replace(tzinfo=timezone.utc)
    
    if created_ts:
        created_ts = created_ts.replace(microsecond=0)
    
    from app import get_socketio
    socketio = get_socketio()
    socketio.emit('note_added', {
        'note_id': note.uuid,
        'text': note.text,
        'target': note.target,
        'created_by': note.created_by,
        'created_at': created_ts.isoformat() if created_ts else None,
        'player_id': note.player_id,
        'player_name': player_name,
        'player_display': player_display
    }, room=f'match_{match_id}')
    
    return jsonify({'success': True, 'note_id': note.uuid})


@bp.route('/<tournament_url>/assign-notes-to-point', methods=['POST'])
@login_required
def assign_notes_to_point(tournament_url):
    """Assign selected notes to a specific point."""
    point_id = request.json.get('point_id')
    note_ids = request.json.get('note_ids', [])
    
    if not point_id or not note_ids:
        return jsonify({'success': False, 'error': 'Point ID and note IDs required'})
    
    point = Point.query.get(point_id)
    if not point:
        return jsonify({'success': False, 'error': 'Point not found'})
    
    match = Match.query.get(point.match)
    if not match or match.event != tournament_url:
        return jsonify({'success': False, 'error': 'Match not found'})
    
    if not is_head_ref(tournament_url, current_user.id):
        return jsonify({'success': False, 'error': 'Not authorized'})
    
    assigned_count = 0
    for note_id in note_ids:
        note = MatchNote.query.get(note_id)
        if note and note.match == point.match and note.point_id is None:
            note.point_id = point_id
            assigned_count += 1
    
    db.session.commit()
    
    return jsonify({'success': True, 'assigned_count': assigned_count})


@bp.route('/<tournament_url>/get-point-notes')
@login_required
def get_point_notes(tournament_url):
    """Get notes for a specific point."""
    match_id = request.args.get('match_id')
    point_id = request.args.get('point_id')
    
    if not match_id or not point_id:
        return jsonify({'success': False, 'error': 'Match ID and Point ID required'})
    
    match = Match.query.get(match_id)
    if not match or match.event != tournament_url:
        return jsonify({'success': False, 'error': 'Match not found'})
    
    if not can_head_ref_match(tournament_url, current_user.id, match=match):
        return jsonify({'success': False, 'error': 'Not authorized'})
    
    notes = MatchNote.query.filter_by(match=match_id, point_id=point_id).order_by(MatchNote.created_at.desc()).all()
    
    notes_data = []
    for note in notes:
        player_name = None
        player_display = None
        if note.player_id:
            player = Player.query.get(note.player_id)
            if player:
                player_name = player.name
                reg = PlayerRegistration.query.filter_by(event=tournament_url, player=player.id).first()
                if reg:
                    if getattr(reg, 'jersey_name', None) and getattr(reg, 'jersey_number', None):
                        player_display = f"{reg.jersey_name} #{reg.jersey_number}"
                    elif getattr(reg, 'jersey_name', None):
                        player_display = reg.jersey_name
                    elif getattr(reg, 'jersey_number', None):
                        player_display = f"#{reg.jersey_number}"
                if not player_display:
                    player_display = player.name
        
        created_ts = note.created_at
        if created_ts and created_ts.tzinfo is None:
            created_ts = created_ts.replace(tzinfo=timezone.utc)
        if created_ts:
            created_ts = created_ts.replace(microsecond=0)
        
        # Determine team_id if target is TEAM1 or TEAM2
        team_id = None
        if note.target in ['TEAM1', 'team1']:
            team_id = match.team1
        elif note.target in ['TEAM2', 'team2']:
            team_id = match.team2
        
        notes_data.append({
            'uuid': note.uuid,
            'text': note.text,
            'target': note.target,
            'created_by': note.created_by,
            'created_at': created_ts.isoformat() if created_ts else None,
            'player_id': note.player_id,
            'player_name': player_name,
            'player_display': player_display,
            'team_id': team_id
        })
    
    return jsonify({'success': True, 'notes': notes_data})


@bp.route('/<tournament_url>/add-point-note', methods=['POST'])
@login_required
def add_point_note(tournament_url):
    """Add a note directly to a point."""
    match_id = request.json.get('match_id')
    point_id = request.json.get('point_id')
    text = request.json.get('text')
    target = request.json.get('target', 'MATCH')
    player_id = request.json.get('player_id')
    
    if not match_id or not point_id or not text:
        return jsonify({'success': False, 'error': 'Match ID, Point ID, and text required'})
    
    match = Match.query.get(match_id)
    if not match or match.event != tournament_url:
        return jsonify({'success': False, 'error': 'Match not found'})
    
    if not can_head_ref_match(tournament_url, current_user.id, match=match):
        return jsonify({'success': False, 'error': 'Not authorized'})
    
    point = Point.query.get(point_id)
    if not point or point.match != match_id:
        return jsonify({'success': False, 'error': 'Point not found'})
    
    note = MatchNote(
        match=match_id,
        point_id=point_id,
        text=text,
        target=target,
        created_by=current_user.id,
        player_id=player_id if player_id else None
    )
    db.session.add(note)
    db.session.commit()
    
    player_name = None
    player_display = None
    if note.player_id:
        player = Player.query.get(note.player_id)
        if player:
            player_name = player.name
            reg = PlayerRegistration.query.filter_by(event=tournament_url, player=player.id).first()
            if reg:
                if getattr(reg, 'jersey_name', None) and getattr(reg, 'jersey_number', None):
                    player_display = f"{reg.jersey_name} #{reg.jersey_number}"
                elif getattr(reg, 'jersey_name', None):
                    player_display = reg.jersey_name
                elif getattr(reg, 'jersey_number', None):
                    player_display = f"#{reg.jersey_number}"
            if not player_display:
                player_display = player.name
    
    created_ts = note.created_at
    if created_ts and created_ts.tzinfo is None:
        created_ts = created_ts.replace(tzinfo=timezone.utc)
    if created_ts:
        created_ts = created_ts.replace(microsecond=0)
    
    from app import get_socketio
    socketio = get_socketio()
    socketio.emit('note_added', {
        'note_id': note.uuid,
        'text': note.text,
        'target': note.target,
        'created_by': note.created_by,
        'created_at': created_ts.isoformat() if created_ts else None,
        'player_id': note.player_id,
        'player_name': player_name,
        'player_display': player_display,
        'point_id': point_id
    }, room=f'match_{match_id}')
    
    return jsonify({'success': True, 'note_id': note.uuid})


@bp.route('/<tournament_url>/delete-point-note', methods=['POST'])
@login_required
def delete_point_note(tournament_url):
    """Delete a note from a point."""
    note_id = request.json.get('note_id')
    
    if not note_id:
        return jsonify({'success': False, 'error': 'Note ID required'})
    
    note = MatchNote.query.get(note_id)
    if not note:
        return jsonify({'success': False, 'error': 'Note not found'})
    
    match = Match.query.get(note.match)
    if not match or match.event != tournament_url:
        return jsonify({'success': False, 'error': 'Match not found'})
    
    if not is_head_ref(tournament_url, current_user.id):
        return jsonify({'success': False, 'error': 'Not authorized'})
    
    db.session.delete(note)
    db.session.commit()
    
    return jsonify({'success': True})


@bp.route('/<tournament_url>/unassign-notes-from-point', methods=['POST'])
@login_required
def unassign_notes_from_point(tournament_url):
    """Unassign notes from a point."""
    point_id = request.json.get('point_id')
    note_ids = request.json.get('note_ids', [])
    
    if not point_id or not note_ids:
        return jsonify({'success': False, 'error': 'Point ID and note IDs required'})
    
    point = Point.query.get(point_id)
    if not point:
        return jsonify({'success': False, 'error': 'Point not found'})
    
    match = Match.query.get(point.match)
    if not match or match.event != tournament_url:
        return jsonify({'success': False, 'error': 'Match not found'})
    
    if not is_head_ref(tournament_url, current_user.id):
        return jsonify({'success': False, 'error': 'Not authorized'})
    
    unassigned_count = 0
    for note_id in note_ids:
        note = MatchNote.query.get(note_id)
        if note and note.point_id == point_id:
            note.point_id = None
            unassigned_count += 1
    
    db.session.commit()
    
    return jsonify({'success': True, 'unassigned_count': unassigned_count})

