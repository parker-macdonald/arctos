"""
Match operation routes (start, run, finalize, view).
"""
from flask import Blueprint, render_template, request, redirect, flash, jsonify
from flask_login import login_required, current_user
from datetime import datetime, timezone
import json
from models import (
    Match, Tournament, Point, PlayerRegistration, Player, db
)
from app.filters import is_head_ref
from app.utils.helpers import check_tournament_access
from app.utils.dependencies import apply_match_dependencies
from app.utils.scheduling import update_dynamic_schedule_after_completion, mark_dependent_matches_time_finalized

bp = Blueprint('matches', __name__)


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
    
    gamestate = {}
    if match.gamestate:
        try:
            gamestate = json.loads(match.gamestate)
        except:
            gamestate = {}
    
    is_head_ref_flag = is_head_ref(tournament_url, current_user.id) if current_user.is_authenticated and current_user.__class__.__name__ == 'Player' else False
    
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

    return render_template('match_page_websocket.html', 
                         tournament=tournament, 
                         match=match, 
                         points=points,
                         gamestate=gamestate,
                         is_head_ref=is_head_ref_flag,
                         computed_end_time=computed_end_time,
                         actual_end_time=actual_end_time)


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
    
    if not is_head_ref(tournament_url, current_user.id):
        flash('You are not authorized to start matches for this tournament', 'error')
        return redirect(f'/{tournament_url}/schedule')
    
    if match.status != 'NOT_STARTED':
        flash('This match has already been started or completed', 'error')
        return redirect(f'/{tournament_url}/schedule')
    
    if not match.team1 or not match.team2 or not (match.refs or match.refs_initial):
        flash('Cannot start match - teams and refs not yet determined', 'error')
        return redirect(f'/{tournament_url}/schedule')
    
    # For dynamic matches, require dependencies to be completed (or marked ready)
    if match.dynamic:
        try:
            from app.utils.scheduling import get_match_dependencies
            deps = get_match_dependencies(match, tournament_url)
        except Exception:
            deps = []
        all_deps_finished = (len(deps) == 0) or all(d.status == 'COMPLETED' for d in deps)
        # Also allow if gamestate says ready_to_start
        is_ready_flag = False
        if match.gamestate:
            try:
                gs = json.loads(match.gamestate)
                is_ready_flag = bool(gs.get('ready_to_start'))
            except Exception:
                is_ready_flag = False
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

    if not is_head_ref(tournament_url, current_user.id):
        return jsonify({'success': False, 'error': 'Not authorized'})

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
        MatchNote.target.in_(['TEAM1', 'team1', 'TEAM2', 'team2'])
    ).all()

    filtered_team_notes = []
    for n in team_target_notes:
        if n.match in team1_match_ids and (n.target == 'TEAM1' or n.target == 'team1'):
            filtered_team_notes.append(n)
        elif n.match in team2_match_ids and (n.target == 'TEAM2' or n.target == 'team2'):
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
        notes_data.append({
            'text': n.text,
            'target': n.target,
            'player_name': player_name,
            'player_display': player_display,
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
    
    if not is_head_ref(tournament_url, current_user.id):
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

    # Enforce that no player appears on both teams
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

    gamestate = {
        'notes': request.form.get('match_notes', ''),
        'team1_players': team1_players,
        'team2_players': team2_players,
        'started_by': current_user.id,
        'started_at': datetime.utcnow().isoformat()
    }
    
    if match.type == 'STONES':
        stones_per_set = request.form.get('stones_per_set')
        if stones_per_set:
            try:
                stones_per_set = int(stones_per_set)
                gamestate['stones_per_set'] = stones_per_set
                gamestate['stones_remaining'] = stones_per_set
            except ValueError:
                flash('Invalid stones per set value', 'error')
                return redirect(f'/{tournament_url}/start-match?id={match.uuid}')
    match.gamestate = json.dumps(gamestate)
    
    db.session.commit()
    
    # Mark dependent matches as time finalized when this match starts
    try:
        mark_dependent_matches_time_finalized(match, tournament_url)
        # Also update predicted times immediately based on this start
        from app.utils.scheduling import recompute_all_match_times
        recompute_all_match_times(tournament_url)
        db.session.commit()
    except Exception as e:
        print(f"Error marking dependent matches time finalized: {e}")
    
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
    
    if not is_head_ref(tournament_url, current_user.id):
        flash('You are not authorized to run matches for this tournament', 'error')
        return redirect(f'/{tournament_url}/schedule')
    
    tournament = Tournament.query.get(tournament_url)
    points = Point.query.filter_by(match=match.uuid).order_by(Point.stamp).all()
    
    gamestate = {}
    if match.gamestate:
        try:
            gamestate = json.loads(match.gamestate)
        except:
            gamestate = {}
    
    team1_players = []
    team2_players = []
    if gamestate.get('team1_players'):
        player_ids = gamestate['team1_players']
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
    
    if gamestate.get('team2_players'):
        player_ids = gamestate['team2_players']
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
                         gamestate=gamestate,
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
    
    if not is_head_ref(tournament_url, current_user.id):
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

                point_notes_map.setdefault(n.point_id, []).append({
                    'text': n.text,
                    'target': n.target,
                    'player_name': player_name,
                    'player_display': player_display,
                    'created_at': n.created_at.isoformat() if getattr(n, 'created_at', None) else None,
                })
    
    gamestate = {}
    if match.gamestate:
        try:
            gamestate = json.loads(match.gamestate)
        except:
            gamestate = {}
    
    team1_score = sum(1 for p in points if p.winner == 'TEAM1' and not p.rerolled)
    team2_score = sum(1 for p in points if p.winner == 'TEAM2' and not p.rerolled)

    return render_template('finalize_match.html',
                         tournament=tournament,
                         match=match,
                         points=points,
                         point_notes_map=point_notes_map,
                         stones_elapsed_map=stones_elapsed_map,
                         team1_score=team1_score,
                         team2_score=team2_score,
                         gamestate=gamestate)


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
    
    if not is_head_ref(tournament_url, current_user.id):
        flash('You are not authorized to finalize matches for this tournament', 'error')
        return redirect(f'/{tournament_url}/schedule')
    
    match.status = 'COMPLETED'
    # Note: end_time may need to be added to Match model if not present
    
    match_winner = request.form.get('match_winner')
    if not match_winner:
        flash('Please select a match winner', 'error')
        return redirect(f'/{tournament_url}/finalize-match?id={match_id}')
    
    gamestate = {}
    if match.gamestate:
        try:
            gamestate = json.loads(match.gamestate)
        except:
            gamestate = {}
    
    # Record completion time on the match using local server time (naive)
    match.completed_time = datetime.now()
    gamestate['finalized_by'] = current_user.id
    gamestate['final_notes'] = request.form.get('final_notes', '')
    gamestate['match_winner'] = match_winner
    
    team1_signature = request.form.get('team1_signature')
    team2_signature = request.form.get('team2_signature')
    if team1_signature:
        gamestate['team1_signature'] = team1_signature
    if team2_signature:
        gamestate['team2_signature'] = team2_signature
    
    match.gamestate = json.dumps(gamestate)
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
    
    try:
        update_dynamic_schedule_after_completion(tournament_url, match)
    except Exception as e:
        print(f"Dynamic scheduling update error for match {match.name}: {e}")
    
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
    
    if not is_head_ref(tournament_url, current_user.id):
        return jsonify({'success': False, 'error': 'Not authorized'})
    
    points = Point.query.filter_by(match=match_id).order_by(Point.stamp).all()
    points_data = []
    for p in points:
        points_data.append({
            'uuid': p.uuid,
            'set_number': p.set_number,
            'winner': p.winner,
            'rerolled': p.rerolled,
            'stamp': p.stamp.isoformat() if p.stamp else None,
            'end_stamp': p.end_stamp.isoformat() if p.end_stamp else None,
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
    
    # Get stones remaining from gamestate
    gamestate = {}
    if match.gamestate:
        try:
            gamestate = json.loads(match.gamestate)
        except:
            gamestate = {}
    
    stones_remaining = gamestate.get('stones_remaining', None)
    
    # Build points data
    points_data = []
    for p in points:
        points_data.append({
            'uuid': p.uuid,
            'set_number': p.set_number,
            'winner': p.winner,
            'rerolled': p.rerolled,
            'stamp': p.stamp.isoformat() if p.stamp else None,
            'end_stamp': p.end_stamp.isoformat() if p.end_stamp else None,
        })
    
    # Get finalized_at from gamestate if match is completed
    finalized_at = None
    if match.status == 'COMPLETED' and 'finalized_at' in gamestate:
        finalized_at = gamestate['finalized_at']
    
    return jsonify({
        'match_id': match.uuid,
        'status': match.status,
        'team1_score': team1_score,
        'team2_score': team2_score,
        'scores_by_set': scores_by_set,
        'stones_remaining': stones_remaining,
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
    
    if not match_id:
        return jsonify({'success': False, 'error': 'Match ID required'}), 400
    
    match = Match.query.get(match_id)
    if not match or match.event != tournament_url:
        return jsonify({'success': False, 'error': 'Match not found'}), 404
    
    if not is_head_ref(tournament_url, current_user.id):
        return jsonify({'success': False, 'error': 'Not authorized'}), 403
    
    new_point = Point(
        match=match_id,
        set_number=set_number,
        stamp=datetime.now(timezone.utc)
    )
    db.session.add(new_point)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'point_id': new_point.uuid,
        'set_number': new_point.set_number,
        'stamp': new_point.stamp.isoformat(),
        'end_stamp': new_point.end_stamp.isoformat() if new_point.end_stamp else None
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
    
    if not is_head_ref(tournament_url, current_user.id):
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
        'end_stamp': point.end_stamp.isoformat() if point.end_stamp else None
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
    
    if not is_head_ref(tournament_url, current_user.id):
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
    
    if not is_head_ref(tournament_url, current_user.id):
        return jsonify({'success': False, 'error': 'Not authorized'}), 403
    
    gamestate = {}
    if match.gamestate:
        try:
            gamestate = json.loads(match.gamestate)
        except:
            gamestate = {}
    
    gamestate['stones_remaining'] = stones_remaining
    match.gamestate = json.dumps(gamestate)
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
    
    if not is_head_ref(tournament_url, current_user.id):
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
    
    if not is_head_ref(tournament_url, current_user.id):
        return jsonify({'success': False, 'error': 'Not authorized'}), 403
    
    match.status = 'COMPLETED'
    db.session.commit()
    
    return jsonify({'success': True, 'match_id': match_id, 'status': 'COMPLETED'})


@bp.route('/stones')
def stones_player():
    """Stones audio player page with server time synchronization."""
    return render_template('stones_player.html')


@bp.route('/server-time')
def server_time():
    """Return current server time in unix timestamp format."""
    import time
    return jsonify({
        'server_time': time.time(),
        'timestamp': datetime.now(timezone.utc).isoformat()
    })

