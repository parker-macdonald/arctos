"""
Match operation routes (start, run, finalize, view).
"""
from flask import Blueprint, render_template, request, redirect, flash, jsonify
from flask_login import login_required, current_user
from datetime import datetime, timezone
import json
from models import (
    Match, Tournament, Point, PlayerRegistration, Player, Field, db
)
from app.filters import is_head_ref
from app.utils.helpers import check_tournament_access, can_head_ref_match
from app.utils.dependencies import apply_match_dependencies
from app.utils.scheduling import recompute_all_match_times


bp = Blueprint('matches', __name__)


@bp.route('/api/scoreboard')
def scoreboard():
    """Scoreboard page for OBS overlay. Public endpoint."""
    from flask import make_response
    
    tournament_url = request.args.get('tournament')
    field_name = request.args.get('field')
    
    if not tournament_url or not field_name:
        return render_template('scoreboard.html', error='Tournament and field parameters required'), 400
    
    # Find the active match on this field (only IN_PROGRESS)
    match = Match.query.filter_by(event=tournament_url, field=field_name, status='IN_PROGRESS').first()
    
    # Get team information helper
    from models import Team, TeamRegistration
    def get_team_info(m):
        if not m:
            return None, None, None, None
        team1_obj = Team.query.get(m.team1) if m.team1 else None
        team2_obj = Team.query.get(m.team2) if m.team2 else None
        
        # Get team names - prefer initial (for dynamic teams), then registration pseudonym, then team name
        # Handle empty strings as well as None
        team1_name = TeamRegistration.query.filter_by(event=tournament_url, team=m.team1).first().pseudonym if m.team1 else m.team1_initial
        team2_name = TeamRegistration.query.filter_by(event=tournament_url, team=m.team2).first().pseudonym if m.team2 else m.team2_initial
        
        # Only include photos if there's an actual team object with a photo (not dynamic teams)
        team1_photo = team1_obj.profile_photo if (team1_obj and team1_obj.profile_photo and m.team1) else None
        team2_photo = team2_obj.profile_photo if (team2_obj and team2_obj.profile_photo and m.team2) else None
        return team1_name, team2_name, team1_photo, team2_photo
    
    # If there's an active match, show it
    if match:
        team1_name, team2_name, team1_photo, team2_photo = get_team_info(match)
        
        # Get points and calculate scores by set
        points = Point.query.filter_by(match=match.uuid).order_by(Point.stamp).all()
        
        # Calculate scores by set
        sets = sorted(set(p.set_number for p in points if p.set_number))
        scores_by_set = {}
        for set_num in sets:
            set_points = [p for p in points if p.set_number == set_num and not p.rerolled]
            scores_by_set[set_num] = {
                'team1_score': sum(1 for p in set_points if p.winner == 'TEAM1'),
                'team2_score': sum(1 for p in set_points if p.winner == 'TEAM2')
            }
        
        # For STONES matches, get stones info
        stones_info = None
        if match.set_type == 'STONES':
            stones_info = {
                'stones_per_set': match.stones_per_set or match.nstonesperset or 100,
                'stones_remaining': match.stones_remaining
            }
        
        response = make_response(render_template(
            'scoreboard.html',
            match=match,
            team1_name=team1_name,
            team2_name=team2_name,
            team1_photo=team1_photo,
            team2_photo=team2_photo,
            scores_by_set=scores_by_set,
            sets=sets,
            stones_info=stones_info,
            tournament_url=tournament_url,
            field_name=field_name,
            show_between_matches=False
        ))
        # Cache the HTML page for 1 second (short cache since it updates frequently)
        response.cache_control.max_age = 1
        return response
    
    # No active match - find previous and next matches
    # Get all matches on this field, ordered by time
    all_field_matches = Match.query.filter_by(event=tournament_url, field=field_name)\
        .order_by(Match.nominal_start_time.asc(), Match.completed_time.asc()).all()
    
    # Find most recent completed match (previous) - skip BREAK/JOIN matches
    prev_match = None
    for m in reversed(all_field_matches):
        if m.status == 'COMPLETED' and m.completed_time and m.schedule_type not in ('BREAK', 'JOIN'):
            prev_match = m
            break
    
    # Find next match (not started or ready to start) - skip BREAK/JOIN matches
    next_match = None
    for m in all_field_matches:
        if m.schedule_type not in ('BREAK', 'JOIN') and (m.status in ('NOT_STARTED', 'IN_PROGRESS') or (m.status == 'COMPLETED' and not m.completed_time)):
            next_match = m
            break
    
    # If no matches found at all
    if not prev_match and not next_match:
        response = make_response(render_template('scoreboard.html', error='No match found on this field', tournament_url=tournament_url, field_name=field_name), 404)
        response.cache_control.max_age = 1
        return response
    
    # Get team info for previous and next matches
    if prev_match:
        prev_team1_name, prev_team2_name, prev_team1_photo, prev_team2_photo = get_team_info(prev_match)
        # Ensure we always have names (fallback if somehow None)
        prev_team1_name = prev_team1_name or 'Team 1'
        prev_team2_name = prev_team2_name or 'Team 2'
    else:
        prev_team1_name, prev_team2_name, prev_team1_photo, prev_team2_photo = None, None, None, None
    
    if next_match:
        next_team1_name, next_team2_name, next_team1_photo, next_team2_photo = get_team_info(next_match)
        # Ensure we always have names (fallback if somehow None)
        next_team1_name = next_team1_name or 'Team 1'
        next_team2_name = next_team2_name or 'Team 2'
    else:
        next_team1_name, next_team2_name, next_team1_photo, next_team2_photo = None, None, None, None
    
    # Determine winner for previous match
    prev_winner = None
    if prev_match and prev_match.match_winner:
        prev_winner = prev_match.match_winner
    
    response = make_response(render_template(
        'scoreboard.html',
        match=None,
        show_between_matches=True,
        prev_match=prev_match,
        prev_team1_name=prev_team1_name,
        prev_team2_name=prev_team2_name,
        prev_team1_photo=prev_team1_photo,
        prev_team2_photo=prev_team2_photo,
        prev_winner=prev_winner,
        next_match=next_match,
        next_team1_name=next_team1_name,
        next_team2_name=next_team2_name,
        next_team1_photo=next_team1_photo,
        next_team2_photo=next_team2_photo,
        tournament_url=tournament_url,
        field_name=field_name
    ))
    response.cache_control.max_age = 1
    return response


@bp.route('/api/scoreboard-state')
def scoreboard_state():
    """Get scoreboard state as JSON for polling. Public endpoint."""
    tournament_url = request.args.get('tournament')
    field_name = request.args.get('field')
    
    if not tournament_url or not field_name:
        return jsonify({'error': 'Tournament and field parameters required'}), 400
    
    # Find the active match on this field (only IN_PROGRESS)
    match = Match.query.filter_by(event=tournament_url, field=field_name, status='IN_PROGRESS').first()
    
    # Get team information helper
    from models import Team, TeamRegistration
    def get_team_info(m):
        if not m:
            return None, None, None, None
        team1_obj = Team.query.get(m.team1) if m.team1 else None
        team2_obj = Team.query.get(m.team2) if m.team2 else None
        
        # Get team names - prefer initial (for dynamic teams), then registration pseudonym, then team name
        # Handle empty strings as well as None
        team1_name = TeamRegistration.query.filter_by(event=tournament_url, team=m.team1).first().pseudonym if m.team1 else m.team1_initial
        team2_name = TeamRegistration.query.filter_by(event=tournament_url, team=m.team2).first().pseudonym if m.team2 else m.team2_initial
        
        # Only include photos if there's an actual team object with a photo (not dynamic teams)
        team1_photo = team1_obj.profile_photo if (team1_obj and team1_obj.profile_photo and m.team1) else None
        team2_photo = team2_obj.profile_photo if (team2_obj and team2_obj.profile_photo and m.team2) else None
        return team1_name, team2_name, team1_photo, team2_photo
    
    # If there's an active match, return match state
    if match:
        team1_name, team2_name, team1_photo, team2_photo = get_team_info(match)
        
        # Get points and calculate scores by set
        points = Point.query.filter_by(match=match.uuid).order_by(Point.stamp).all()
        
        # Calculate scores by set
        sets = sorted(set(p.set_number for p in points if p.set_number))
        scores_by_set = {}
        for set_num in sets:
            set_points = [p for p in points if p.set_number == set_num and not p.rerolled]
            scores_by_set[set_num] = {
                'team1_score': sum(1 for p in set_points if p.winner == 'TEAM1'),
                'team2_score': sum(1 for p in set_points if p.winner == 'TEAM2')
            }
        
        # For STONES matches, get stones info
        stones_info = None
        if match.set_type == 'STONES':
            stones_info = {
                'stones_per_set': match.stones_per_set or match.nstonesperset or 100,
                'stones_remaining': match.stones_remaining
            }
        
        return jsonify({
            'has_active_match': True,
            'match_id': match.uuid,
            'team1_name': team1_name,
            'team2_name': team2_name,
            'team1_photo': team1_photo,
            'team2_photo': team2_photo,
            'scores_by_set': scores_by_set,
            'sets': sets,
            'stones_info': stones_info,
            'timestamp': datetime.now(timezone.utc).isoformat()
        })
    
    # No active match - find previous and next matches
    # Get all matches on this field, ordered by time
    all_field_matches = Match.query.filter_by(event=tournament_url, field=field_name)\
        .order_by(Match.nominal_start_time.asc(), Match.completed_time.asc()).all()
    
    # Find most recent completed match (previous) - skip BREAK/JOIN matches
    prev_match = None
    for m in reversed(all_field_matches):
        if m.status == 'COMPLETED' and m.completed_time and m.schedule_type not in ('BREAK', 'JOIN'):
            prev_match = m
            break
    
    # Find next match (not started or ready to start) - skip BREAK/JOIN matches
    next_match = None
    for m in all_field_matches:
        if m.schedule_type not in ('BREAK', 'JOIN') and (m.status in ('NOT_STARTED', 'IN_PROGRESS') or (m.status == 'COMPLETED' and not m.completed_time)):
            next_match = m
            break
    
    # Get team info for previous and next matches
    prev_data = None
    if prev_match:
        prev_team1_name, prev_team2_name, prev_team1_photo, prev_team2_photo = get_team_info(prev_match)
        prev_team1_name = prev_team1_name or 'Team 1'
        prev_team2_name = prev_team2_name or 'Team 2'
        prev_data = {
            'team1_name': prev_team1_name,
            'team2_name': prev_team2_name,
            'team1_photo': prev_team1_photo,
            'team2_photo': prev_team2_photo,
            'winner': prev_match.match_winner
        }
    
    next_data = None
    if next_match:
        next_team1_name, next_team2_name, next_team1_photo, next_team2_photo = get_team_info(next_match)
        next_team1_name = next_team1_name or 'Team 1'
        next_team2_name = next_team2_name or 'Team 2'
        next_data = {
            'team1_name': next_team1_name,
            'team2_name': next_team2_name,
            'team1_photo': next_team1_photo,
            'team2_photo': next_team2_photo
        }
    
    return jsonify({
        'has_active_match': False,
        'prev_match': prev_data,
        'next_match': next_data,
        'timestamp': datetime.now(timezone.utc).isoformat()
    })


@bp.route('/<tournament_url>/match')
def match_page(tournament_url):
    """Match viewing page."""
    match_id = request.args.get('id')
    match_name = request.args.get('name')
    
    if not match_id and not match_name:
        flash('Match ID or name required', 'error')
        return redirect(f'/{tournament_url}/schedule')
    
    has_access, tournament = check_tournament_access(tournament_url)
    if not has_access or not tournament:
        return redirect('/')
    
    if match_id:
        match = Match.query.filter_by(uuid=match_id, event=tournament_url).first_or_404()
    else:
        match = Match.query.filter_by(name=match_name, event=tournament_url).first_or_404()
    
    points = Point.query.filter_by(match=match.uuid).order_by(Point.stamp).all()
    
    is_head_ref_flag = can_head_ref_match(tournament_url, current_user.id, match=match) if current_user.is_authenticated and current_user.__class__.__name__ == 'Player' else False
    
    # Get match notes and point notes
    match_notes = []
    point_notes_map = {}
        from models import MatchNote, PlayerRegistration, Player
    
    # Get match-level notes (point_id is None) - only for head refs
    if is_head_ref_flag:
        notes = MatchNote.query.filter_by(match=match.uuid, point_id=None).order_by(MatchNote.created_at.desc()).all()
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
            # Determine team_id if target is TEAM1 or TEAM2
            team_id = None
            if note.target=='team1':
                team_id = match.team1
            elif note.target=='team2':
                team_id = match.team2
            
            match_notes.append({
                'text': note.text,
                'target': note.target,
                'player_id': note.player_id,
                'player_name': player_name,
                'player_display': player_display,
                'team_id': team_id,
                'created_at': note.created_at.isoformat() if note.created_at else None,
            })
        
    # Get point-specific notes - point notes (target='match') visible to everyone
    # Team and player notes only visible to head refs
        if points:
            point_ids = [p.uuid for p in points if getattr(p, 'uuid', None)]
            if point_ids:
                point_notes = MatchNote.query.filter_by(match=match.uuid).filter(
                    MatchNote.point_id.in_(point_ids)
                ).order_by(MatchNote.created_at.asc()).all()
                for n in point_notes:
                # Filter: only show point notes (target='match') to everyone
                # Team and player notes are only visible to head refs
                if not is_head_ref_flag and n.target != 'match':
                    continue
                
                    player_name = None
                    player_display = None
                    if n.player_id:
                        pl = Player.query.get(n.player_id)
                        if pl:
                            player_name = pl.name
                            reg = PlayerRegistration.query.filter_by(event=tournament_url, player=pl.id).first()
                            if reg:
                                if getattr(reg, 'jersey_name', None) and getattr(reg, 'jersey_number', None):
                                    player_display = f"{reg.jersey_name} #{reg.jersey_number}"
                                elif getattr(reg, 'jersey_name', None):
                                    player_display = reg.jersey_name
                                elif getattr(reg, 'jersey_number', None):
                                    player_display = f"#{reg.jersey_number}"
                            if not player_display:
                                player_display = pl.name
                    # Determine team_id if target is TEAM1 or TEAM2
                    team_id = None
                    if n.target=='team1':
                        team_id = match.team1
                    elif n.target=='team2':
                        team_id = match.team2
                    
                    point_notes_map.setdefault(n.point_id, []).append({
                        'text': n.text,
                        'target': n.target,
                        'player_id': n.player_id,
                        'player_name': player_name,
                        'player_display': player_display,
                        'team_id': team_id,
                        'created_at': n.created_at.isoformat() if getattr(n, 'created_at', None) else None,
                    })
    
    # Compute end time for display
    computed_end_time = None
    actual_end_time = match.completed_time
    try:
        if match.nominal_length:
            base_start = match.confirmed_start_time or match.nominal_start_time
            if base_start:
                from datetime import timedelta
                computed_end_time = base_start + timedelta(minutes=match.nominal_length)
    except Exception:
        computed_end_time = None

    # Get all camera URLs and filter to only those active during the match
    camera_url = None
    available_cameras = []  # List of dicts: {index, url, stream_start_time, type, video_path, camera_id, session_id}
    
            from app.utils.camera_helpers import parse_camera_urls
            from datetime import datetime, timezone
            import json
    import os
    from flask import current_app
    
    # Get stream start times and recorded videos from match (check even if no field cameras)
                stream_starts = {}
    recorded_videos = []  # List of recorded video sessions
    camera_urls = []
    
                if match.camera_stream_starts:
                    try:
            stream_starts_data = json.loads(match.camera_stream_starts)
            
            # Parse the new format: camera_id -> recording info (single or list)
            for camera_id, recording_data in stream_starts_data.items():
                # Handle both single recording and list of recordings
                recordings = recording_data if isinstance(recording_data, list) else [recording_data]
                
                for recording in recordings:
                    # Check if this is a recorded video (has video_path)
                    if isinstance(recording, dict) and 'video_path' in recording:
                        video_path = recording.get('video_path', '')
                        session_id = recording.get('session_id', '')
                        start_timestamp = recording.get('start_timestamp')
                        start_time = recording.get('start_time')
                        
                        # Check if video file exists
                        if video_path:
                            # Convert relative path to absolute
                            video_full_path = os.path.join(
                                current_app.root_path,
                                '../static',
                                video_path
                            )
                            
                            if os.path.exists(video_full_path):
                                # Load metadata.json to get point_timestamps
                                point_timestamps = None
                                video_dir = os.path.dirname(video_full_path)
                                metadata_path = os.path.join(video_dir, 'metadata.json')
                                if os.path.exists(metadata_path):
                                    try:
                                        with open(metadata_path, 'r') as f:
                                            video_metadata = json.load(f)
                                            point_timestamps = video_metadata.get('point_timestamps')
                                    except (json.JSONDecodeError, IOError) as e:
                                        print(f"Error reading metadata.json: {e}")
                                
                                recorded_videos.append({
                                    'camera_id': camera_id,
                                    'session_id': session_id,
                                    'video_path': video_path,  # Keep relative path for URL
                                    'start_timestamp': start_timestamp,
                                    'start_time': start_time,
                                    'point_timestamps': point_timestamps,
                                    'type': 'recorded'
                                })
                    
                    # Also handle old format (just stream start time string)
                    elif isinstance(recording, str) or (isinstance(recording, dict) and 'start_time' in recording and 'video_path' not in recording):
                        # This is the old format, skip for now (handled below)
                        pass
        except (json.JSONDecodeError, TypeError) as e:
            print(f"Error parsing camera_stream_starts: {e}")
            # Try old format
            try:
                # Old format: index -> stream_start_time string
                stream_starts = stream_starts_data if isinstance(stream_starts_data, dict) else {}
            except:
                stream_starts = {}
    
    # Get YouTube cameras from field configuration (if field exists)
    if match.field:
        field_obj = Field.query.filter_by(event=tournament_url, name=match.field).first()
        if field_obj and field_obj.camera:
            camera_urls = parse_camera_urls(field_obj.camera)
            
            # Include YouTube cameras from field configuration
            if camera_urls:
                for idx, url in enumerate(camera_urls):
                    stream_start_str = stream_starts.get(str(idx))  # JSON keys are strings
                    
                    # For old format compatibility
                    if not stream_start_str and isinstance(stream_starts, dict):
                        stream_start_str = stream_starts.get(str(idx))
                    
                        available_cameras.append({
                            'index': idx,
                            'url': url,
                        'stream_start_time': stream_start_str if stream_start_str else None,
                        'type': 'youtube'
                    })
            
    # Add recorded videos (only for completed matches)
    if match.status == 'COMPLETED' and recorded_videos:
        # Add recorded videos with unique indices (starting after YouTube cameras)
        for idx, recording in enumerate(recorded_videos):
            available_cameras.append({
                'index': len(camera_urls) + idx,  # Continue indexing after YouTube cameras
                'url': None,  # No YouTube URL for recorded videos
                'stream_start_time': recording.get('start_time') or (datetime.fromtimestamp(int(recording.get('start_timestamp')) / 1000).isoformat() + 'Z' if recording.get('start_timestamp') else None),
                'type': 'recorded',
                'video_path': recording['video_path'],
                'camera_id': recording.get('camera_id', 'unknown'),
                'session_id': recording.get('session_id', ''),
                'point_timestamps': recording.get('point_timestamps')
                        })
            
            # Use first available camera for backward compatibility
            if available_cameras:
        first_cam = available_cameras[0]
        if first_cam.get('type') == 'youtube':
            camera_url = first_cam['url']
            
            # Debug: log camera availability
    if not available_cameras and match.field:
        field_obj = Field.query.filter_by(event=tournament_url, name=match.field).first()
        if field_obj and field_obj.camera:
                print(f"Warning: No cameras available for match {match.uuid} on field {match.field}. Field has {len(camera_urls)} camera(s). Match status: {match.status}")

    return render_template('match_page_websocket.html', 
                         tournament=tournament, 
                         match=match, 
                         points=points,
                         is_head_ref=is_head_ref_flag,
                         computed_end_time=computed_end_time,
                         actual_end_time=actual_end_time,
                         match_notes=match_notes,
                         point_notes_map=point_notes_map,
                         camera_url=camera_url,
                         available_cameras=available_cameras)


@bp.route('/<tournament_url>/start-match')
@login_required
def start_match(tournament_url):
    """Match setup page for head refs."""
    match_id = request.args.get('id')
    if not match_id:
        flash('Match ID required', 'error')
        return redirect(f'/{tournament_url}/schedule')
    
    match = Match.query.get(match_id)
    if not match or match.event != tournament_url:
        flash('Match not found', 'error')
        return redirect(f'/{tournament_url}/schedule')
    
    if not can_head_ref_match(tournament_url, current_user.id, match=match):
        flash('You are not authorized to start matches for this tournament', 'error')
        return redirect(f'/{tournament_url}/schedule')
    
    if match.status != 'NOT_STARTED':
        flash('This match has already been started or completed', 'error')
        return redirect(f'/{tournament_url}/schedule')
    
    if not match.team1 or not match.team2 or not (match.refs or match.refs_initial):
        flash('Cannot start match - teams and refs not yet determined', 'error')
        return redirect(f'/{tournament_url}/schedule')
    
    # For dynamic matches, require dependencies to be completed (or marked ready)
    if match.schedule_type != 'STATIC':
        try:
            from app.utils.scheduling import get_match_dependencies
            deps = get_match_dependencies(match, tournament_url)
        except Exception:
            deps = []
        all_deps_finished = (len(deps) == 0) or all(d.status == 'COMPLETED' for d in deps)
        # Also allow if ready_to_start flag is set
        is_ready_flag = match.ready_to_start or False
        if not (all_deps_finished or is_ready_flag):
            flash('This match cannot be started yet. Dependencies are not completed.', 'error')
            return redirect(f'/{tournament_url}/schedule')

    tournament = Tournament.query.get(tournament_url)
    
    team1_players = db.session.query(PlayerRegistration, Player).join(
        Player, PlayerRegistration.player == Player.id
    ).filter(
        PlayerRegistration.event == tournament_url,
        PlayerRegistration.team == match.team1,
        PlayerRegistration.status == 'CONFIRMED'
    ).all()
    
    team2_players = db.session.query(PlayerRegistration, Player).join(
        Player, PlayerRegistration.player == Player.id
    ).filter(
        PlayerRegistration.event == tournament_url,
        PlayerRegistration.team == match.team2,
        PlayerRegistration.status == 'CONFIRMED'
    ).all()
    
    all_players = db.session.query(PlayerRegistration, Player).join(
        Player, PlayerRegistration.player == Player.id
    ).filter(
        PlayerRegistration.event == tournament_url,
        PlayerRegistration.status == 'CONFIRMED'
    ).all()
    
    from models import Injury
    injuries_map = {}
    try:
        all_player_ids = set([pr.player for pr, _ in all_players] +
                              [pr.player for pr, _ in team1_players] +
                              [pr.player for pr, _ in team2_players])
        if all_player_ids:
            active_injuries = Injury.query.filter(
                Injury.player.in_(list(all_player_ids)), 
                Injury.active.is_(True)
            ).all()
            for inj in active_injuries:
                injuries_map.setdefault(inj.player, []).append(inj.message)
    except Exception:
        injuries_map = {}
    
    return render_template('start_match.html', 
                         tournament=tournament, 
                         match=match, 
                         team1_players=team1_players, 
                         team2_players=team2_players, 
                         all_players=all_players,
                         injuries_map=injuries_map)


@bp.route('/<tournament_url>/get-selection-notes')
@login_required
def get_selection_notes(tournament_url):
    """Get notes relevant to team and selected players."""
    match_id = request.args.get('match_id')
    team_side = request.args.get('team')
    player_ids_csv = request.args.get('player_ids', '')

    if not match_id or team_side not in ('team1', 'team2'):
        return jsonify({'success': False, 'error': 'match_id and team required'})

    match = Match.query.get(match_id)
    if not match or match.event != tournament_url:
        return jsonify({'success': False, 'error': 'Match not found'})

    if not can_head_ref_match(tournament_url, current_user.id, match=match):
        return jsonify({'success': False, 'error': 'bruh ur not a head ref'})

    team_id = match.team1 if team_side == 'team1' else match.team2
    if not team_id:
        return jsonify({'success': True, 'notes': []})

    selected_player_ids = [pid.strip() for pid in player_ids_csv.split(',') if pid.strip()]

    team1_matches = Match.query.filter_by(event=tournament_url, team1=team_id).all()
    team2_matches = Match.query.filter_by(event=tournament_url, team2=team_id).all()
    team1_match_ids = {m.uuid for m in team1_matches}
    team2_match_ids = {m.uuid for m in team2_matches}

    from models import MatchNote
    player_notes = []
    if selected_player_ids:
        # Only include notes from matches in this tournament
        player_notes = db.session.query(MatchNote).join(Match, Match.uuid == MatchNote.match).filter(
            Match.event == tournament_url,
            MatchNote.player_id.in_(selected_player_ids)
        ).all()

    team_target_notes = MatchNote.query.filter(
        MatchNote.match.in_(list(team1_match_ids | team2_match_ids))
    ).filter(
        MatchNote.target.in_(['team1', 'team2'])
    ).all()

    filtered_team_notes = []
    for n in team_target_notes:
        if n.match in team1_match_ids and (n.target == 'team1'):
            filtered_team_notes.append(n)
        elif n.match in team2_match_ids and (n.target == 'team2'):
            filtered_team_notes.append(n)

    all_notes = {}
    for n in player_notes + filtered_team_notes:
        all_notes[getattr(n, 'uuid', id(n))] = n

    notes_data = []
    for n in all_notes.values():
        player_name = None
        player_display = None
        if n.player_id:
            p = Player.query.get(n.player_id)
            if p:
                player_name = p.name
                reg = PlayerRegistration.query.filter_by(event=tournament_url, player=p.id).first()
                if reg:
                    if getattr(reg, 'jersey_name', None) and getattr(reg, 'jersey_number', None):
                        player_display = f"{reg.jersey_name} #{reg.jersey_number}"
                    elif getattr(reg, 'jersey_name', None):
                        player_display = reg.jersey_name
                    elif getattr(reg, 'jersey_number', None):
                        player_display = f"#{reg.jersey_number}"
                if not player_display:
                    player_display = p.name
        # Get match to determine team_id
        match_obj = Match.query.get(n.match) if n.match else None
        team_id = None
        if match_obj:
            if n.target=='team1':
                team_id = match_obj.team1
            elif n.target=='team2':
                team_id = match_obj.team2
        
        notes_data.append({
            'text': n.text,
            'target': n.target,
            'player_id': n.player_id,
            'player_name': player_name,
            'player_display': player_display,
            'team_id': team_id,
        })

    try:
        notes_data.sort(key=lambda x: x.get('created_at') or '', reverse=True)
    except Exception:
        pass

    return jsonify({'success': True, 'notes': notes_data})


@bp.route('/<tournament_url>/start-match', methods=['POST'])
@login_required
def start_match_post(tournament_url):
    """Handle match start form submission."""
    match_id = request.form.get('match_id')
    if not match_id:
        flash('Match ID required', 'error')
        return redirect(f'/{tournament_url}/schedule')
    
    match = Match.query.get(match_id)
    if not match or match.event != tournament_url:
        flash('Match not found', 'error')
        return redirect(f'/{tournament_url}/schedule')
    
    if not can_head_ref_match(tournament_url, current_user.id, match=match):
        flash('You are not authorized to start matches for this tournament', 'error')
        return redirect(f'/{tournament_url}/schedule')
    
    if match.status != 'NOT_STARTED':
        flash('This match has already been started or completed', 'error')
        return redirect(f'/{tournament_url}/schedule')
    
    match.status = 'IN_PROGRESS'
    # Use local server time (naive) for display consistency on localhost
    confirmed_start = datetime.now()
    match.confirmed_start_time = confirmed_start
    
    # Parse selected players from hidden inputs (comma-separated)
    raw_team1 = (request.form.get('team1_players') or '').strip()
    raw_team2 = (request.form.get('team2_players') or '').strip()
    team1_players = [pid for pid in (raw_team1.split(',') if raw_team1 else []) if pid]
    team2_players = [pid for pid in (raw_team2.split(',') if raw_team2 else []) if pid]

    # Enforce that no player appears on both teams (should be prevented by UI, but check server-side too)
    overlap = set(team1_players) & set(team2_players)
    if overlap:
        flash('A player cannot be selected for both teams', 'error')
        return redirect(f'/{tournament_url}/start-match?id={match.uuid}')

    # Enforce roster size if configured
    tournament_obj = Tournament.query.get(tournament_url)
    max_roster = getattr(tournament_obj, 'max_team_size_field', None)
    try:
        max_roster = int(max_roster) if max_roster is not None else None
    except Exception:
        max_roster = None
    if max_roster and (len(team1_players) > max_roster or len(team2_players) > max_roster):
        flash('Too many players selected for a team', 'error')
        return redirect(f'/{tournament_url}/start-match?id={match.uuid}')

    # Deduplicate preserving order
    def dedup(seq):
        seen = set()
        out = []
        for x in seq:
            if x not in seen:
                seen.add(x)
                out.append(x)
        return out
    team1_players = dedup(team1_players)
    team2_players = dedup(team2_players)

    import json
    match.initial_notes = request.form.get('match_notes', '')
    match.team1_players = json.dumps(team1_players)
    match.team2_players = json.dumps(team2_players)
    match.started_by = current_user.id
    match.started_at = datetime.utcnow()
    
    if match.set_type == 'STONES':
        stones_per_set = request.form.get('stones_per_set')
        if stones_per_set:
            try:
                stones_per_set = int(stones_per_set)
            except ValueError:
                flash('Invalid stones per set value', 'error')
                return redirect(f'/{tournament_url}/start-match?id={match.uuid}')
        else:
            # Use match's nstonesperset value or default to 100
            stones_per_set = match.nstonesperset or 100
        match.stones_per_set = stones_per_set
        match.stones_remaining = stones_per_set
    
    # Get camera stream start times for all cameras on this field
    if match.field:
        field_obj = Field.query.filter_by(event=tournament_url, name=match.field).first()
        if field_obj and field_obj.camera:
            from app.utils.camera_helpers import get_all_camera_stream_starts
            stream_starts = get_all_camera_stream_starts(field_obj)
            if stream_starts:
                match.camera_stream_starts = json.dumps(stream_starts)
    
    db.session.commit()
    
    # Update predicted times first, then mark dependent matches as time finalized
    try:
        # First recompute all match times to update nominal_start_time for all matches
        recompute_all_match_times(tournament_url)
        # Then mark dependent matches as time finalized (this will update JOIN/BREAK times and propagate)
        db.session.commit()
    except Exception as e:
        print(f"Error updating schedule and marking dependent matches time finalized: {e}")
    
    flash('Match started successfully!', 'success')
    return redirect(f'/{tournament_url}/run-match?id={match.uuid}')


@bp.route('/<tournament_url>/run-match')
@login_required
def run_match(tournament_url):
    """Match running page for head refs."""
    match_id = request.args.get('id')
    if not match_id:
        flash('Match ID required', 'error')
        return redirect(f'/{tournament_url}/schedule')
    
    match = Match.query.get(match_id)
    if not match or match.event != tournament_url:
        flash('Match not found', 'error')
        return redirect(f'/{tournament_url}/schedule')
    
    if match.status == 'COMPLETED':
        flash('This match has already been completed', 'error')
        return redirect(f'/{tournament_url}/schedule')
    
    if not can_head_ref_match(tournament_url, current_user.id, match=match):
        flash('You are not authorized to run matches for this tournament', 'error')
        return redirect(f'/{tournament_url}/schedule')
    
    tournament = Tournament.query.get(tournament_url)
    points = Point.query.filter_by(match=match.uuid).order_by(Point.stamp).all()
    
    team1_players = []
    team2_players = []
    if match.team1_players:
        try:
            player_ids = json.loads(match.team1_players)
            for pid in player_ids:
                pr = PlayerRegistration.query.filter_by(
                    event=tournament_url,
                    player=pid,
                    status='CONFIRMED'
                ).first()
                if pr:
                    player = Player.query.get(pid)
                    if player:
                        team1_players.append((pr, player))
        except (json.JSONDecodeError, TypeError):
            pass
    
    if match.team2_players:
        try:
            player_ids = json.loads(match.team2_players)
            for pid in player_ids:
                pr = PlayerRegistration.query.filter_by(
                    event=tournament_url,
                    player=pid,
                    status='CONFIRMED'
                ).first()
                if pr:
                    player = Player.query.get(pid)
                    if player:
                        team2_players.append((pr, player))
        except (json.JSONDecodeError, TypeError):
            pass
    
    # Build match_players for player autocomplete in notes modal
    match_players = []
    for pr, player in team1_players + team2_players:
        display = player.name
        if getattr(pr, 'jersey_name', None) and getattr(pr, 'jersey_number', None):
            display = f"{pr.jersey_name} #{pr.jersey_number}"
        elif getattr(pr, 'jersey_name', None):
            display = pr.jersey_name
        elif getattr(pr, 'jersey_number', None):
            display = f"#{pr.jersey_number}"
        match_players.append({'player_id': player.id, 'name': player.name, 'display': display})

    return render_template('run_match_websocket.html',
                         tournament=tournament,
                         match=match,
                         points=points,
                         team1_players=team1_players,
                         team2_players=team2_players,
                         match_players=match_players)


@bp.route('/<tournament_url>/finalize-match')
@login_required
def finalize_match(tournament_url):
    """Match finalization page."""
    match_id = request.args.get('id')
    if not match_id:
        flash('Match ID required', 'error')
        return redirect(f'/{tournament_url}/schedule')
    
    match = Match.query.get(match_id)
    if not match or match.event != tournament_url:
        flash('Match not found', 'error')
        return redirect(f'/{tournament_url}/schedule')
    
    if match.status == 'COMPLETED':
        flash('This match has already been completed', 'error')
        return redirect(f'/{tournament_url}/schedule')
    
    if not can_head_ref_match(tournament_url, current_user.id, match=match):
        flash('You are not authorized to finalize matches for this tournament', 'error')
        return redirect(f'/{tournament_url}/schedule')
    
    tournament = Tournament.query.get(tournament_url)
    points = Point.query.filter_by(match=match.uuid).order_by(Point.stamp).all()

    from models import MatchNote
    point_notes_map = {}
    stones_elapsed_map = {}
    
    def compute_stones_elapsed(start_dt, end_dt):
        try:
            if not start_dt or not end_dt:
                return 0
            start_epoch = start_dt.timestamp()
            end_epoch = end_dt.timestamp()
            start_count = int(start_epoch // 1.5)
            end_count = int(end_epoch // 1.5)
            val = end_count - start_count
            return val if val >= 0 else 0
        except Exception:
            return 0
    
    if points:
        point_ids = [p.uuid for p in points if getattr(p, 'uuid', None)]
        for p in points:
            stones_elapsed_map[p.uuid] = compute_stones_elapsed(getattr(p, 'stamp', None), getattr(p, 'end_stamp', None))
        if point_ids:
            notes = MatchNote.query.filter_by(match=match.uuid).filter(
                MatchNote.point_id.in_(point_ids)
            ).order_by(MatchNote.created_at.asc()).all()
            for n in notes:
                player_name = None
                player_display = None
                if n.player_id:
                    pl = Player.query.get(n.player_id)
                    if pl:
                        player_name = pl.name
                        reg = PlayerRegistration.query.filter_by(event=tournament_url, player=pl.id).first()
                        if reg:
                            if getattr(reg, 'jersey_name', None) and getattr(reg, 'jersey_number', None):
                                player_display = f"{reg.jersey_name} #{reg.jersey_number}"
                            elif getattr(reg, 'jersey_name', None):
                                player_display = reg.jersey_name
                            elif getattr(reg, 'jersey_number', None):
                                player_display = f"#{reg.jersey_number}"
                        if not player_display:
                            player_display = pl.name

                # Determine team_id if target is TEAM1 or TEAM2
                team_id = None
                if n.target=='team1':
                    team_id = match.team1
                elif n.target=='team2':
                    team_id = match.team2
                
                point_notes_map.setdefault(n.point_id, []).append({
                    'text': n.text,
                    'target': n.target,
                    'player_id': n.player_id,
                    'player_name': player_name,
                    'player_display': player_display,
                    'team_id': team_id,
                    'created_at': n.created_at.isoformat() if getattr(n, 'created_at', None) else None,
                })
    
    team1_score = sum(1 for p in points if p.winner == 'TEAM1' and not p.rerolled)
    team2_score = sum(1 for p in points if p.winner == 'TEAM2' and not p.rerolled)

    return render_template('finalize_match.html',
                         tournament=tournament,
                         match=match,
                         points=points,
                         point_notes_map=point_notes_map,
                         stones_elapsed_map=stones_elapsed_map,
                         team1_score=team1_score,
                         team2_score=team2_score)


@bp.route('/<tournament_url>/finalize-match', methods=['POST'])
@login_required
def finalize_match_post(tournament_url):
    """Handle match finalization."""
    match_id = request.form.get('match_id')
    if not match_id:
        flash('Match ID required', 'error')
        return redirect(f'/{tournament_url}/schedule')
    
    match = Match.query.get(match_id)
    if not match or match.event != tournament_url:
        flash('Match not found', 'error')
        return redirect(f'/{tournament_url}/schedule')
    
    if not can_head_ref_match(tournament_url, current_user.id, match=match):
        flash('You are not authorized to finalize matches for this tournament', 'error')
        return redirect(f'/{tournament_url}/schedule')
    
    match.status = 'COMPLETED'
    # Note: end_time may need to be added to Match model if not present
    
    match_winner = request.form.get('match_winner')
    if not match_winner:
        flash('Please select a match winner', 'error')
        return redirect(f'/{tournament_url}/finalize-match?id={match_id}')
    
    
    # Record completion time on the match using local server time (naive)
    match.completed_time = datetime.now()
    match.finalized_by = current_user.id
    match.final_notes = request.form.get('final_notes', '')
    match.match_winner = match_winner
    match.finalized_at = datetime.now()
    
    # Refresh camera stream start times when match ends (in case streams started late)
    if match.field:
        field_obj = Field.query.filter_by(event=tournament_url, name=match.field).first()
        if field_obj and field_obj.camera:
            from app.utils.camera_helpers import get_all_camera_stream_starts
            stream_starts = get_all_camera_stream_starts(field_obj)
            if stream_starts:
                # Merge with existing stream starts (don't overwrite if already set)
                existing_starts = {}
                if match.camera_stream_starts:
                    try:
                        existing_starts = json.loads(match.camera_stream_starts)
                    except json.JSONDecodeError:
                        pass
                # Update with any new stream starts
                existing_starts.update(stream_starts)
                match.camera_stream_starts = json.dumps(existing_starts)
    
    team1_signature = request.form.get('team1_signature')
    team2_signature = request.form.get('team2_signature')
    if team1_signature:
        match.team1_signature = team1_signature
    if team2_signature:
        match.team2_signature = team2_signature
    db.session.commit()
    
    from app import get_socketio
    socketio = get_socketio()
    socketio.emit('match_completed', {
        'match_id': match_id,
        'status': 'COMPLETED',
        'winner': match_winner,
        'finalized_at': (match.completed_time.isoformat() if match.completed_time else None)
    }, room=f'match_{match_id}')

    try:
        apply_match_dependencies(tournament_url, match)
    except Exception as e:
        print(f"Dependency update error for match {match.name}: {e}")
    
    # Update dynamic schedule after completion (marks dependent matches as ready to start)
    # try:
    #     update_dynamic_schedule_after_completion(tournament_url, match)
    # except Exception as e:
    #     print(f"Dynamic scheduling update error for match {match.name}: {e}")
    
    # Recompute all match times with the new algorithm
    try:
        from app.utils.scheduling import recompute_all_match_times
        recompute_all_match_times(tournament_url)
        db.session.commit()
    except Exception as e:
        print(f"Error recomputing match times: {e}")
    
    flash('Match finalized successfully!', 'success')
    return redirect(f'/{tournament_url}/schedule')


@bp.route('/<tournament_url>/get-points')
@login_required
def get_points(tournament_url):
    """Get points for a match."""
    match_id = request.args.get('match_id')
    if not match_id:
        return jsonify({'success': False, 'error': 'Match ID required'})
    
    match = Match.query.get(match_id)
    if not match or match.event != tournament_url:
        return jsonify({'success': False, 'error': 'Match not found'})
    
    if not can_head_ref_match(tournament_url, current_user.id, match=match):
        return jsonify({'success': False, 'error': 'Not authorized'})
    
    points = Point.query.filter_by(match=match_id).order_by(Point.stamp).all()
    match = Match.query.get(match_id)
    points_data = []
    for p in points:
        points_data.append({
            'uuid': p.uuid,
            'set_number': p.set_number,
            'winner': p.winner,
            'rerolled': p.rerolled,
            'stamp': p.stamp.isoformat() if p.stamp else None,
            'end_stamp': p.end_stamp.isoformat() if p.end_stamp else None,
            'stones_at_start': p.stones_at_start if match and match.set_type == 'STONES' else None,
        })
    
    return jsonify({'success': True, 'points': points_data})


@bp.route('/<tournament_url>/match-state')
def match_state(tournament_url):
    """Get current match state for polling. Public endpoint."""
    match_id = request.args.get('id')
    if not match_id:
        return jsonify({'error': 'Match ID required'}), 400
    
    match = Match.query.filter_by(uuid=match_id, event=tournament_url).first()
    if not match:
        return jsonify({'error': 'Match not found'}), 404
    
    points = Point.query.filter_by(match=match.uuid).order_by(Point.stamp).all()
    
    # Calculate scores
    team1_score = sum(1 for p in points if p.winner == 'TEAM1' and not p.rerolled)
    team2_score = sum(1 for p in points if p.winner == 'TEAM2' and not p.rerolled)
    
    # Scores by set
    sets = sorted(set(p.set_number for p in points))
    scores_by_set = {}
    for set_num in sets:
        set_points = [p for p in points if p.set_number == set_num]
        scores_by_set[set_num] = {
            'team1_score': sum(1 for p in set_points if p.winner == 'TEAM1' and not p.rerolled),
            'team2_score': sum(1 for p in set_points if p.winner == 'TEAM2' and not p.rerolled)
        }
    
    # Build points data
    points_data = []
    for p in points:
        # Ensure timestamps are timezone-aware UTC for proper JavaScript parsing
        # (timezone is already imported at top of file)
        stamp_iso = None
        end_stamp_iso = None
        
        if p.stamp:
            # Convert naive UTC to timezone-aware UTC
            if p.stamp.tzinfo is None:
                stamp_dt = p.stamp.replace(tzinfo=timezone.utc)
            else:
                stamp_dt = p.stamp
            stamp_iso = stamp_dt.isoformat().replace('+00:00', 'Z')
        
        if p.end_stamp:
            if p.end_stamp.tzinfo is None:
                end_stamp_dt = p.end_stamp.replace(tzinfo=timezone.utc)
            else:
                end_stamp_dt = p.end_stamp
            end_stamp_iso = end_stamp_dt.isoformat().replace('+00:00', 'Z')
        
        points_data.append({
            'uuid': p.uuid,
            'set_number': p.set_number,
            'winner': p.winner,
            'rerolled': p.rerolled,
            'stamp': stamp_iso,
            'end_stamp': end_stamp_iso,
            'stones_at_start': p.stones_at_start if match.set_type == 'STONES' else None,
        })
    
    # Get finalized_at if match is completed
    finalized_at = None
    if match.status == 'COMPLETED' and match.finalized_at:
        finalized_at = match.finalized_at.isoformat()
    
    return jsonify({
        'match_id': match.uuid,
        'status': match.status,
        'team1_score': team1_score,
        'team2_score': team2_score,
        'scores_by_set': scores_by_set,
        'points': points_data,
        'finalized_at': finalized_at,
        'timestamp': datetime.now(timezone.utc).isoformat()
    })


@bp.route('/<tournament_url>/match-actions/add-point', methods=['POST'])
@login_required
def add_point(tournament_url):
    """Add a new point to a match."""
    match_id = request.json.get('match_id')
    set_number = request.json.get('set_number', 1)
    timestamp = request.json.get('timestamp')
    stones_at_start = request.json.get('stones_at_start')  # Client-computed value
    
    if not match_id:
        return jsonify({'success': False, 'error': 'Match ID required'}), 400
    
    match = Match.query.get(match_id)
    if not match or match.event != tournament_url:
        return jsonify({'success': False, 'error': 'Match not found'}), 404
    
    if not can_head_ref_match(tournament_url, current_user.id, match=match):
        return jsonify({'success': False, 'error': 'Not authorized'}), 403
    
    new_point = Point(
        match=match_id,
        set_number=set_number,
        stamp=datetime.fromtimestamp(timestamp/1000, tz=timezone.utc)
    )
    
    # For STONES matches, use client-computed stones_at_start value
    # This ensures accuracy even if the request takes time to send
    if match.set_type == 'STONES':
        if stones_at_start is not None and isinstance(stones_at_start, int):
            new_point.stones_at_start = stones_at_start
        else:
            # Fallback to server-side value if client didn't send it or it's invalid
            print(f"Warning: Invalid stones_at_start from client ({stones_at_start}). Falling back to server value: {match.stones_remaining}")
        new_point.stones_at_start = match.stones_remaining
    
    # Calculate and store camera stream timestamp if cameras are configured
    if match.field:
        field_obj = Field.query.filter_by(event=tournament_url, name=match.field).first()
        if field_obj and field_obj.camera and match.camera_stream_starts:
            from app.utils.camera_helpers import parse_camera_urls, calculate_stream_timestamp
            try:
                stream_starts = json.loads(match.camera_stream_starts)
                camera_urls = parse_camera_urls(field_obj.camera)
                
                # Use primary camera (index 0) if available
                # Note: JSON keys are strings, so use '0' not 0
                if '0' in stream_starts and len(camera_urls) > 0:
                    stream_timestamp = calculate_stream_timestamp(new_point.stamp, stream_starts['0'])
                    if stream_timestamp is not None:
                        new_point.camera_index = 0
                        new_point.stream_timestamp = stream_timestamp
            except (json.JSONDecodeError, KeyError, ValueError) as e:
                print(f"Error calculating camera stream timestamp: {e}")
    
    db.session.add(new_point)
    db.session.commit()
    
    # Ensure timestamps are timezone-aware UTC
    # (timezone is already imported at top of file)
    stamp_iso = None
    end_stamp_iso = None
    
    if new_point.stamp:
        if new_point.stamp.tzinfo is None:
            stamp_dt = new_point.stamp.replace(tzinfo=timezone.utc)
        else:
            stamp_dt = new_point.stamp
        stamp_iso = stamp_dt.isoformat().replace('+00:00', 'Z')
    
    if new_point.end_stamp:
        if new_point.end_stamp.tzinfo is None:
            end_stamp_dt = new_point.end_stamp.replace(tzinfo=timezone.utc)
        else:
            end_stamp_dt = new_point.end_stamp
        end_stamp_iso = end_stamp_dt.isoformat().replace('+00:00', 'Z')
    
    return jsonify({
        'success': True,
        'point_id': new_point.uuid,
        'set_number': new_point.set_number,
        'stamp': stamp_iso,
        'end_stamp': end_stamp_iso,
        'stones_at_start': new_point.stones_at_start if match.set_type == 'STONES' else None
    })


@bp.route('/<tournament_url>/match-actions/update-point', methods=['POST'])
@login_required
def update_point(tournament_url):
    """Update a point."""
    point_id = request.json.get('point_id')
    if not point_id:
        return jsonify({'success': False, 'error': 'Point ID required'}), 400
    
    point = Point.query.get(point_id)
    if not point:
        return jsonify({'success': False, 'error': 'Point not found'}), 404
    
    match = Match.query.get(point.match)
    if not match or match.event != tournament_url:
        return jsonify({'success': False, 'error': 'Match not found'}), 404
    
    if not can_head_ref_match(tournament_url, current_user.id, match=match):
        return jsonify({'success': False, 'error': 'Not authorized'}), 403
    
    data = request.json
    if 'winner' in data:
        point.winner = data['winner'] if data['winner'] != 'none' else None
    if 'rerolled' in data:
        point.rerolled = data['rerolled']
    if 'notes' in data:
        point.notes = data['notes']
    if 'set_number' in data:
        point.set_number = data['set_number']
    if 'end_stamp' in data:
        point.end_stamp = datetime.fromisoformat(data['end_stamp'].replace('Z', '+00:00'))
    
    db.session.commit()
    
    return jsonify({
        'success': True,
        'point_id': point_id,
        'winner': point.winner,
        'rerolled': point.rerolled,
        'notes': point.notes,
        'set_number': point.set_number,
        'end_stamp': point.end_stamp.isoformat() if point.end_stamp else None,
        'nstones': point.nstones
    })


@bp.route('/<tournament_url>/match-actions/delete-point', methods=['POST'])
@login_required
def delete_point_action(tournament_url):
    """Delete a point."""
    point_id = request.json.get('point_id')
    if not point_id:
        return jsonify({'success': False, 'error': 'Point ID required'}), 400
    
    point = Point.query.get(point_id)
    if not point:
        return jsonify({'success': False, 'error': 'Point not found'}), 404
    
    match = Match.query.get(point.match)
    if not match or match.event != tournament_url:
        return jsonify({'success': False, 'error': 'Match not found'}), 404
    
    if not can_head_ref_match(tournament_url, current_user.id, match=match):
        return jsonify({'success': False, 'error': 'Not authorized'}), 403
    
    match_id = point.match
    db.session.delete(point)
    db.session.commit()
    
    return jsonify({'success': True, 'point_id': point_id})


@bp.route('/<tournament_url>/match-actions/update-stones', methods=['POST'])
@login_required
def update_stones(tournament_url):
    """Update stones remaining."""
    match_id = request.json.get('match_id')
    stones_remaining = request.json.get('stones_remaining')
    
    if not match_id or stones_remaining is None:
        return jsonify({'success': False, 'error': 'Match ID and stones_remaining required'}), 400
    
    match = Match.query.get(match_id)
    if not match or match.event != tournament_url:
        return jsonify({'success': False, 'error': 'Match not found'}), 404
    
    if not can_head_ref_match(tournament_url, current_user.id, match=match):
        return jsonify({'success': False, 'error': 'Not authorized'}), 403
    
    match.stones_remaining = stones_remaining
    db.session.commit()
    
    return jsonify({'success': True, 'stones_remaining': stones_remaining})


@bp.route('/<tournament_url>/match-actions/update-set', methods=['POST'])
@login_required
def update_set(tournament_url):
    """Update set number for a point."""
    point_id = request.json.get('point_id')
    set_number = request.json.get('set_number')
    
    if not point_id or set_number is None:
        return jsonify({'success': False, 'error': 'Point ID and set_number required'}), 400
    
    point = Point.query.get(point_id)
    if not point:
        return jsonify({'success': False, 'error': 'Point not found'}), 404
    
    match = Match.query.get(point.match)
    if not match or match.event != tournament_url:
        return jsonify({'success': False, 'error': 'Match not found'}), 404
    
    if not can_head_ref_match(tournament_url, current_user.id, match=match):
        return jsonify({'success': False, 'error': 'Not authorized'}), 403
    
    point.set_number = set_number
    db.session.commit()
    
    return jsonify({'success': True, 'point_id': point_id, 'set_number': set_number})


@bp.route('/<tournament_url>/match-actions/complete-match', methods=['POST'])
@login_required
def complete_match(tournament_url):
    """Mark a match as completed."""
    match_id = request.json.get('match_id')
    if not match_id:
        return jsonify({'success': False, 'error': 'Match ID required'}), 400
    
    match = Match.query.get(match_id)
    if not match or match.event != tournament_url:
        return jsonify({'success': False, 'error': 'Match not found'}), 404
    
    if not can_head_ref_match(tournament_url, current_user.id, match=match):
        return jsonify({'success': False, 'error': 'Not authorized'}), 403
    
    match.status = 'COMPLETED'
    db.session.commit()
    
    return jsonify({'success': True, 'match_id': match_id, 'status': 'COMPLETED'})


@bp.route('/stones')
def stones_player():
    """Stones audio player page with server time synchronization."""
    import os
    from flask import current_app
    from flask_login import current_user
    
    # Hardcoded list of usernames that can see all audio files
    ALLOWED_USERS = os.environ.get('SILLY_USERS', '').split(':')  # Add usernames here
    
    # Get the static folder path
    static_folder = current_app.static_folder
    stones_dir = os.path.join(static_folder, 'stones')
    
    # List all MP3 files in the stones directory
    import re
    mp3_files = []
    if os.path.exists(stones_dir) and os.path.isdir(stones_dir):
        for filename in os.listdir(stones_dir):
            if filename.lower().endswith('.mp3'):
                # Remove extension
                name_without_ext = os.path.splitext(filename)[0]
                # Remove numeric prefix (e.g., "1_", "2_", etc.) for display name
                display_name = re.sub(r'^\d+_', '', name_without_ext)
                # Extract numeric prefix for sorting (default to 0 if no prefix)
                match = re.match(r'^(\d+)_', name_without_ext)
                sort_order = int(match.group(1)) if match else 999999
                # URL-encode the filename for use in URLs
                from urllib.parse import quote
                filename_encoded = quote(filename, safe='')
                
                mp3_files.append({
                    'filename': filename,
                    'filename_encoded': filename_encoded,
                    'display_name': display_name,
                    'sort_order': sort_order
                })
        # Sort by numeric prefix (sort_order), then by filename for consistent ordering
        mp3_files.sort(key=lambda x: (x['sort_order'], x['filename']))
    
    # Filter files based on user permissions
    # Only show "Classic" and "Snare" unless user is in the allowed list
    user_can_see_all = (
        current_user.is_authenticated and 
        current_user.id in ALLOWED_USERS
    )
    
    if not user_can_see_all:
        # Filter to only show "Classic" and "Snare" (case-insensitive)
        mp3_files = [
            f for f in mp3_files 
            if f['display_name'].lower() in ['classic', 'snare']
        ]
    
    return render_template('stones_player.html', mp3_files=mp3_files)


@bp.route('/server-time')
def server_time():
    """Return current server time in unix timestamp format."""
    import time
    return jsonify({
        'server_time': time.time(),
        'timestamp': datetime.now(timezone.utc).isoformat()
    })


@bp.route('/youtube-stream-start')
def youtube_stream_start():
    """Get YouTube live stream start time."""
    import re
    import os
    import requests
    
    video_id = request.args.get('video_id')
    if not video_id:
        return jsonify({'error': 'video_id required'}), 400
    
    # Extract video ID if full URL provided
    patterns = [
        r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/|youtube\.com/v/)([^&\n?#]+)',
        r'^([a-zA-Z0-9_-]{11})$'
    ]
    for pattern in patterns:
        match = re.search(pattern, video_id)
        if match:
            video_id = match.group(1)
            break
    
    # Try to get stream start time from YouTube Data API v3
    api_key = os.environ.get('YOUTUBE_API_KEY')
    if not api_key:
        # If no API key, return null (client will handle gracefully)
        return jsonify({
            'start_time': None,
            'error': 'YouTube API key not configured'
        })
    
    try:
        # Get video details from YouTube Data API v3
        url = f'https://www.googleapis.com/youtube/v3/videos'
        params = {
            'id': video_id,
            'part': 'liveStreamingDetails,snippet',
            'key': api_key
        }
        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()
        
        if not data.get('items'):
            return jsonify({
                'start_time': None,
                'error': 'Video not found'
            })
        
        video = data['items'][0]
        live_details = video.get('liveStreamingDetails', {})
        
        # Get actual start time if available
        actual_start_time = live_details.get('actualStartTime')
        if actual_start_time:
            # YouTube API returns time in ISO 8601 format with 'Z' (UTC)
            # Parse it and ensure it's timezone-aware
            # (datetime and timezone are already imported at top of file)
            start_dt = datetime.fromisoformat(actual_start_time.replace('Z', '+00:00'))
            # Ensure it's UTC timezone-aware
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=timezone.utc)
            # Return in ISO format with timezone info (ensures 'Z' suffix for UTC)
            return jsonify({
                'start_time': start_dt.isoformat().replace('+00:00', 'Z'),
                'video_id': video_id,
                'timezone': 'UTC'
            })
        
        # Stream not started yet
        return jsonify({
            'start_time': None,
            'error': 'Stream has not started'
        })
        
    except requests.exceptions.RequestException as e:
        return jsonify({
            'start_time': None,
            'error': f'Error fetching stream info: {str(e)}'
        }), 500
    except Exception as e:
        return jsonify({
            'start_time': None,
            'error': f'Unexpected error: {str(e)}'
        }), 500

