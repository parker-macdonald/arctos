"""
SocketIO WebSocket event handlers for real-time match updates.
"""
from flask_socketio import emit, join_room, leave_room
from flask_login import current_user
from datetime import datetime
import json
from models import Match, Point, db


def init_websocket_handlers(socketio_instance):
    """Initialize websocket handlers with the socketio instance."""
    @socketio_instance.on('join_match')
    def handle_join_match(data):
        """Join a match room for real-time updates."""
        match_id = data.get('match_id')
        if match_id:
            join_room(f'match_{match_id}')
            emit('status', {'msg': f'Joined match {match_id}'})


    @socketio_instance.on('leave_match')
    def handle_leave_match(data):
        """Leave a match room."""
        match_id = data.get('match_id')
        if match_id:
            leave_room(f'match_{match_id}')


    @socketio_instance.on('update_score')
    def handle_update_score(data):
        """Handle score updates and broadcast to all viewers."""
        match_id = data.get('match_id')
        if not match_id:
            return
        
        match = Match.query.get(match_id)
        if not match:
            return
        
        points = Point.query.filter_by(match=match.uuid).all()
        team1_score = sum(1 for point in points if point.winner == 'TEAM1' and not point.rerolled)
        team2_score = sum(1 for point in points if point.winner == 'TEAM2' and not point.rerolled)
        
        sets = sorted(set(p.set_number for p in points))
        scores_by_set = {}
        for set_num in sets:
            set_points = [p for p in points if p.set_number == set_num]
            scores_by_set[set_num] = {
                'team1_score': sum(1 for p in set_points if p.winner == 'TEAM1' and not p.rerolled),
                'team2_score': sum(1 for p in set_points if p.winner == 'TEAM2' and not p.rerolled)
            }
        
        emit('score_updated', {
            'team1_score': team1_score,
            'team2_score': team2_score,
            'scores_by_set': scores_by_set
        }, room=f'match_{match_id}')


    @socketio_instance.on('update_stones')
    def handle_update_stones(data):
        """Handle stones updates and broadcast to all viewers."""
        match_id = data.get('match_id')
        stones_remaining = data.get('stones_remaining')
        
        if not match_id or stones_remaining is None:
            return
        
        match = Match.query.get(match_id)
        if not match:
            return
        
        match.stones_remaining = stones_remaining
        db.session.commit()
        
        emit('stones_updated', {
            'stones_remaining': stones_remaining
        }, room=f'match_{match_id}')


    @socketio_instance.on('update_point')
    def handle_update_point(data):
        """Handle point updates and broadcast to all viewers."""
        point_id = data.get('point_id')
        if not point_id:
            return
        
        point = Point.query.get(point_id)
        if not point:
            return
        
        if 'winner' in data:
            point.winner = data['winner'] if data['winner'] != 'none' else None
        if 'rerolled' in data:
            point.rerolled = data['rerolled']
        if 'notes' in data:
            point.notes = data['notes']
        if 'set_number' in data:
            point.set_number = data['set_number']
        if 'end_stamp' in data:
            from datetime import timezone as tz
            point.end_stamp = datetime.fromisoformat(data['end_stamp'].replace('Z', '+00:00'))
        
        db.session.commit()
        
        emit('point_updated', {
            'point_id': point_id,
            'winner': point.winner,
            'rerolled': point.rerolled,
            'notes': point.notes,
            'set_number': point.set_number,
            'end_stamp': point.end_stamp.isoformat() if point.end_stamp else None
        }, room=f'match_{point.match}')
        
        points = Point.query.filter_by(match=point.match).all()
        team1_score = sum(1 for p in points if p.winner == 'TEAM1' and not p.rerolled)
        team2_score = sum(1 for p in points if p.winner == 'TEAM2' and not p.rerolled)
        
        sets = sorted(set(p.set_number for p in points))
        scores_by_set = {}
        for set_num in sets:
            set_points = [p for p in points if p.set_number == set_num]
            scores_by_set[set_num] = {
                'team1_score': sum(1 for p in set_points if p.winner == 'TEAM1' and not p.rerolled),
                'team2_score': sum(1 for p in set_points if p.winner == 'TEAM2' and not p.rerolled)
            }
        
        emit('score_updated', {
            'team1_score': team1_score,
            'team2_score': team2_score,
            'scores_by_set': scores_by_set
        }, room=f'match_{point.match}')


    @socketio_instance.on('add_point')
    def handle_add_point(data):
        """Handle new point creation and broadcast to all viewers."""
        match_id = data.get('match_id')
        if not match_id:
            return
        
        new_point = Point(
            match=match_id,
            set_number=data.get('set_number', 1),
            stamp=datetime.utcnow()
        )
        db.session.add(new_point)
        db.session.commit()
        
        emit('point_added', {
            'point_id': new_point.uuid,
            'set_number': new_point.set_number,
            'stamp': new_point.stamp.isoformat(),
            'end_stamp': new_point.end_stamp.isoformat() if new_point.end_stamp else None
        }, room=f'match_{match_id}')
        
        points = Point.query.filter_by(match=match_id).all()
        team1_score = sum(1 for p in points if p.winner == 'TEAM1' and not p.rerolled)
        team2_score = sum(1 for p in points if p.winner == 'TEAM2' and not p.rerolled)
        
        sets = sorted(set(p.set_number for p in points))
        scores_by_set = {}
        for set_num in sets:
            set_points = [p for p in points if p.set_number == set_num]
            scores_by_set[set_num] = {
                'team1_score': sum(1 for p in set_points if p.winner == 'TEAM1' and not p.rerolled),
                'team2_score': sum(1 for p in set_points if p.winner == 'TEAM2' and not p.rerolled)
            }
        
        emit('score_updated', {
            'team1_score': team1_score,
            'team2_score': team2_score,
            'scores_by_set': scores_by_set
        }, room=f'match_{match_id}')


    @socketio_instance.on('delete_point')
    def handle_delete_point(data):
        """Handle point deletion and broadcast to all viewers."""
        point_id = data.get('point_id')
        if not point_id:
            return
        
        point = Point.query.get(point_id)
        if not point:
            return
        
        match_id = point.match
        db.session.delete(point)
        db.session.commit()
        
        emit('point_deleted', {
            'point_id': point_id
        }, room=f'match_{match_id}')
        
        points = Point.query.filter_by(match=match_id).all()
        team1_score = sum(1 for p in points if p.winner == 'TEAM1' and not p.rerolled)
        team2_score = sum(1 for p in points if p.winner == 'TEAM2' and not p.rerolled)
        
        sets = sorted(set(p.set_number for p in points))
        scores_by_set = {}
        for set_num in sets:
            set_points = [p for p in points if p.set_number == set_num]
            scores_by_set[set_num] = {
                'team1_score': sum(1 for p in set_points if p.winner == 'TEAM1' and not p.rerolled),
                'team2_score': sum(1 for p in set_points if p.winner == 'TEAM2' and not p.rerolled)
            }
        
        emit('score_updated', {
            'team1_score': team1_score,
            'team2_score': team2_score,
            'scores_by_set': scores_by_set
        }, room=f'match_{match_id}')


    @socketio_instance.on('note_added')
    def handle_note_added(data):
        """Handle new note addition and broadcast to all viewers."""
        match_id = data.get('match_id')
        text = data.get('text')
        target = data.get('target', 'MATCH')
        
        if not match_id or not text:
            return
        
        from models import MatchNote
        note = MatchNote(
            match=match_id,
            text=text,
            target=target,
            created_by=current_user.id if current_user.is_authenticated else None
        )
        db.session.add(note)
        db.session.commit()
        
        emit('note_added', {
            'note_id': note.uuid,
            'text': note.text,
            'target': note.target,
            'created_by': note.created_by,
            'created_at': note.created_at.isoformat()
        }, room=f'match_{match_id}')


    @socketio_instance.on('update_set')
    def handle_update_set(data):
        """Handle set number updates and broadcast to all viewers."""
        point_id = data.get('point_id')
        set_number = data.get('set_number')
        match_id = data.get('match_id')
        
        if not point_id or set_number is None:
            return
        
        point = Point.query.get(point_id)
        if not point:
            return
        
        point.set_number = set_number
        db.session.commit()
        
        emit('set_updated', {
            'point_id': point_id,
            'set_number': set_number
        }, room=f'match_{match_id}')


    @socketio_instance.on('complete_match')
    def handle_complete_match(data):
        """Handle match completion."""
        match_id = data.get('match_id')
        if not match_id:
            return
        
        match = Match.query.get(match_id)
        if not match:
            return
        
        match.status = 'COMPLETED'
        db.session.commit()
        
        # Recompute all match times after match completion
        try:
            from app.utils.scheduling import recompute_all_match_times
            tournament_url = match.event
            recompute_all_match_times(tournament_url)
            db.session.commit()
        except Exception as e:
            print(f"Error recomputing match times after websocket completion: {e}")
        
        emit('match_completed', {
            'match_id': match_id,
            'status': 'COMPLETED'
        }, room=f'match_{match_id}')
