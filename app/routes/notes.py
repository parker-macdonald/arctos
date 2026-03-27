"""
Match notes management routes.
"""

from flask import Blueprint, request
from flask_login import login_required, current_user
from models import Match, MatchNote, Point, Tournament, db
from app.domain.enums import MatchNoteTarget
from app.filters import is_head_ref
from app.utils.helpers import can_head_ref_match, match_event_urls_for_penalties
from app.serializers.match_note_serializer import MatchNoteSerializer
from app.utils.responses import json_error, json_success

bp = Blueprint("notes", __name__, url_prefix="/_api")


def _match_in_tournament_scope(match, tournament_url):
    """True if match belongs to this event or (for league) any event in the league."""
    tournament = Tournament.query.filter_by(url=tournament_url).first()
    if not tournament:
        return False
    event_urls = match_event_urls_for_penalties(tournament)
    return match.event in event_urls


@bp.route("/<tournament_url>/get-notes")
@login_required
def get_notes(tournament_url):
    """Get notes for a match. For league events, match may be from any event in the league."""
    match_id = request.args.get("match_id")

    if not match_id:
        return json_error("Match ID required")

    match = Match.query.get(match_id)
    if not match or not _match_in_tournament_scope(match, tournament_url):
        return json_error("Match not found")

    if not can_head_ref_match(tournament_url, current_user.id, match=match):
        return json_error("Not authorized")

    point_id = request.args.get("point_id")

    if point_id:
        notes = (
            MatchNote.query.filter_by(match=match_id)
            .filter((MatchNote.point_id == point_id) | (MatchNote.point_id.is_(None)))
            .order_by(MatchNote.created_at.desc())
            .all()
        )
    else:
        notes = (
            MatchNote.query.filter_by(match=match_id, point_id=None)
            .order_by(MatchNote.created_at.desc())
            .all()
        )

    notes_data = []
    for note in notes:
        notes_data.append(
            MatchNoteSerializer.to_dict(note, tournament_url, match=match)
        )

    return json_success({"notes": notes_data})


@bp.route("/<tournament_url>/add-note", methods=["POST"])
@login_required
def add_note(tournament_url):
    """Add a note to a match."""
    match_id = request.json.get("match_id")
    text = request.json.get("text")
    target = request.json.get("target", "MATCH")
    player_id = request.json.get("player_id")

    if not match_id or not text:
        return json_error("Match ID and text required")

    match = Match.query.get(match_id)
    if not match or not _match_in_tournament_scope(match, tournament_url):
        return json_error("Match not found")

    if not can_head_ref_match(tournament_url, current_user.id, match=match):
        return json_error("Not authorized")

    note = MatchNote(
        match=match_id,
        text=text,
        target=target,
        created_by=current_user.id,
        player_id=player_id if player_id else None,
    )
    db.session.add(note)
    db.session.commit()

    return json_success({"note_id": note.uuid})


@bp.route("/<tournament_url>/assign-notes-to-point", methods=["POST"])
@login_required
def assign_notes_to_point(tournament_url):
    """Assign selected notes to a specific point."""
    point_id = request.json.get("point_id")
    note_ids = request.json.get("note_ids", [])

    if not point_id or not note_ids:
        return json_error("Point ID and note IDs required")

    point = Point.query.get(point_id)
    if not point:
        return json_error("Point not found")

    match = Match.query.get(point.match)
    if not match or not _match_in_tournament_scope(match, tournament_url):
        return json_error("Match not found")

    if not is_head_ref(tournament_url, current_user.id):
        return json_error("Not authorized")

    assigned_count = 0
    for note_id in note_ids:
        note = MatchNote.query.get(note_id)
        if note and note.match == point.match and note.point_id is None:
            note.point_id = point_id
            assigned_count += 1

    db.session.commit()

    return json_success({"assigned_count": assigned_count})


@bp.route("/<tournament_url>/get-point-notes")
def get_point_notes(tournament_url):
    """Get notes for a specific point. Point notes (target='match') are visible to everyone.
    Team and player notes are only visible to authorized users."""
    match_id = request.args.get("match_id")
    point_id = request.args.get("point_id")

    if not match_id or not point_id:
        return json_error("Match ID and Point ID required")

    match = Match.query.get(match_id)
    if not match or not _match_in_tournament_scope(match, tournament_url):
        return json_error("Match not found")

    # Check if user is a head ref (for full access to all notes)
    is_head_ref = False
    if current_user.is_authenticated and current_user.__class__.__name__ == "Player":
        is_head_ref = can_head_ref_match(tournament_url, current_user.id, match=match)

    # Get all notes for this point
    notes = (
        MatchNote.query.filter_by(match=match_id, point_id=point_id)
        .order_by(MatchNote.created_at.desc())
        .all()
    )

    notes_data = []
    for note in notes:
        # Filter: only show point notes (target='match') to everyone
        # Team and player notes are only visible to head refs
        if not is_head_ref and note.target != "match":
            continue
        notes_data.append(
            MatchNoteSerializer.to_dict(note, tournament_url, match=match)
        )

    return json_success({"notes": notes_data})


@bp.route("/<tournament_url>/add-point-note", methods=["POST"])
@login_required
def add_point_note(tournament_url):
    """Add a note directly to a point."""
    match_id = request.json.get("match_id")
    point_id = request.json.get("point_id")
    text = request.json.get("text", "")
    target = request.json.get("target", "MATCH")
    player_id = request.json.get("player_id")
    penalty_type_id = request.json.get("penalty_type_id")

    if not match_id or not point_id:
        return json_error("Match ID and Point ID required")

    if not text and not penalty_type_id:
        return json_error("Text or penalty type required")

    match = Match.query.get(match_id)
    if not match or not _match_in_tournament_scope(match, tournament_url):
        return json_error("Match not found")

    if not can_head_ref_match(tournament_url, current_user.id, match=match):
        return json_error("Not authorized")

    point = Point.query.get(point_id)
    if not point or point.match != match_id:
        return json_error("Point not found")

    note = MatchNote(
        match=match_id,
        point_id=point_id,
        text=text,
        target=target,
        created_by=current_user.id,
        player_id=player_id if player_id else None,
        penalty_type_id=penalty_type_id if penalty_type_id else None,
    )
    db.session.add(note)
    db.session.commit()

    return json_success({"note_id": note.uuid})


@bp.route("/<tournament_url>/set-point-note", methods=["POST"])
@login_required
def set_point_note(tournament_url):
    """Set the single point note for a point (target=match). Replaces any existing one."""
    match_id = request.json.get("match_id")
    point_id = request.json.get("point_id")
    text = (request.json.get("text") or "").strip()

    if not match_id or not point_id:
        return json_error("Match ID and Point ID required")

    match = Match.query.get(match_id)
    if not match or not _match_in_tournament_scope(match, tournament_url):
        return json_error("Match not found")

    if not can_head_ref_match(tournament_url, current_user.id, match=match):
        return json_error("Not authorized")

    point = Point.query.get(point_id)
    if not point or point.match != match_id:
        return json_error("Point not found")

    # Remove existing point note(s) for this point (target=match only)
    MatchNote.query.filter_by(
        match=match_id,
        point_id=point_id,
        target=MatchNoteTarget.MATCH,
    ).delete()

    if text:
        note = MatchNote(
            match=match_id,
            point_id=point_id,
            text=text,
            target=MatchNoteTarget.MATCH,
            created_by=current_user.id,
        )
        db.session.add(note)

    db.session.commit()
    return json_success()


@bp.route("/<tournament_url>/delete-point-note", methods=["POST"])
@login_required
def delete_point_note(tournament_url):
    """Delete a note from a point."""
    note_id = request.json.get("note_id")

    if not note_id:
        return json_error("Note ID required")

    note = MatchNote.query.get(note_id)
    if not note:
        return json_error("Note not found")

    match = Match.query.get(note.match)
    if not match or not _match_in_tournament_scope(match, tournament_url):
        return json_error("Match not found")

    from app.utils.helpers import can_head_ref_match

    if not can_head_ref_match(tournament_url, current_user.id, note.match):
        return json_error("Not authorized")

    db.session.delete(note)
    db.session.commit()

    return json_success()


@bp.route("/<tournament_url>/unassign-notes-from-point", methods=["POST"])
@login_required
def unassign_notes_from_point(tournament_url):
    """Unassign notes from a point."""
    point_id = request.json.get("point_id")
    note_ids = request.json.get("note_ids", [])

    if not point_id or not note_ids:
        return json_error("Point ID and note IDs required")

    point = Point.query.get(point_id)
    if not point:
        return json_error("Point not found")

    match = Match.query.get(point.match)
    if not match or not _match_in_tournament_scope(match, tournament_url):
        return json_error("Match not found")

    if not is_head_ref(tournament_url, current_user.id):
        return json_error("Not authorized")

    unassigned_count = 0
    for note_id in note_ids:
        note = MatchNote.query.get(note_id)
        if note and note.point_id == point_id:
            note.point_id = None
            unassigned_count += 1

    db.session.commit()

    return json_success({"unassigned_count": unassigned_count})
