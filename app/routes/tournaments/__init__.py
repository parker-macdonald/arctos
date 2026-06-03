"""Tournament-organiser routes - blueprint package.

Hosts the ``tournaments`` blueprint at ``/_api``.

Routes are split by sub-topic across submodules in this package; all
submodules share the same Blueprint object defined in this file, so
URL endpoint names are stable across moves:

- :mod:`app.routes.tournaments.management` - TO-side tournament/league
  CRUD, fields, tags, TO membership.
- :mod:`app.routes.tournaments.scheduling` - schedule editing, recompute,
  push-back, import/export, DSL validation.
- :mod:`app.routes.tournaments.recordings` - cameras, recording/preview
  endpoints, ffmpeg finalisation, user-upload pipeline.

The :data:`executor` is a Flask-Executor used to run ffmpeg finalisation
off the request thread; we only ever want one worker at a time because
ffmpeg already parallelises internally.
"""

from flask import Blueprint
from flask_executor import Executor

from models import Match

# for finalizing recordings which calls ffmpeg
# only one worker bc ffmpeg does its own parallelism
# so we only ever want to run one at a time
executor = Executor()

bp = Blueprint("tournaments", __name__, url_prefix="/_api")


def update_match_previous_link(match: Match, prev_match_id: str, tournament_url: str, is_new: bool = False) -> None:
    """
    Update the previous_match link for a match, maintaining a doubly linked list structure.

    When inserting a match after prev_match, if prev_match already has a next_match:
    1. Store the old next_match of prev_match
    2. Set the current match's previous_match to prev_match
    3. Set prev_match's next_match to the current match
    4. Set the current match's next_match to the old next_match (if it existed)
    5. Set the old next_match's previous_match to the current match (if it existed)
    6. If updating (not new), handle cleanup of old previous_match's next_match

    This properly inserts the match into the chain: ... -> prev_match -> match -> old_next_match -> ...

    Args:
        match: The match to update
        prev_match_id: UUID of the match to set as previous_match
        tournament_url: Tournament URL for validation
        is_new: True if this is a new match, False if updating existing match
    """
    prev_match = Match.query.filter_by(uuid=prev_match_id, event=tournament_url).first()
    if not prev_match:
        return

    # Store old previous_match and next_match for cleanup (only for updates)
    old_prev_id = match.previous_match if not is_new else None
    old_next_id = match.next_match if not is_new else None

    # Store the old next_match of prev_match (before we change it)
    prev_match_old_next_id = prev_match.next_match

    # Set the current match's previous_match to prev_match
    match.previous_match = prev_match_id

    # Set prev_match's next_match to this match
    prev_match.next_match = match.uuid

    # If prev_match had a next_match that isn't this match, link it to this match
    if prev_match_old_next_id and prev_match_old_next_id != match.uuid:
        prev_match_old_next = Match.query.filter_by(uuid=prev_match_old_next_id, event=tournament_url).first()
        if prev_match_old_next:
            # Set the current match's next_match to the old next_match
            match.next_match = prev_match_old_next_id
            # Set the old next_match's previous_match to this match
            prev_match_old_next.previous_match = match.uuid
    else:
        # No old next_match from prev_match
        # If updating an existing match, preserve its existing next_match if it's still valid
        # (only clear if this is a new match or if we're explicitly changing the chain)
        if is_new:
            match.next_match = None
        # For updates, preserve the existing next_match - it will be handled by cleanup logic below if needed

    # If updating and had an old previous_match, handle cleanup
    if old_prev_id and old_prev_id != prev_match_id:
        old_prev_match = Match.query.filter_by(uuid=old_prev_id, event=tournament_url).first()
        if old_prev_match:
            # If old_prev_match's next_match pointed to this match, we need to update it
            if old_prev_match.next_match == match.uuid:
                # The old previous match's next should now point to this match's old next (if any)
                old_prev_match.next_match = old_next_id if old_next_id != old_prev_id else None
                # If we set old_prev_match.next_match to something, update that match's previous_match
                if old_prev_match.next_match:
                    old_next_of_old_prev = Match.query.filter_by(
                        uuid=old_prev_match.next_match, event=tournament_url
                    ).first()
                    if old_next_of_old_prev:
                        old_next_of_old_prev.previous_match = old_prev_id

    # If updating and had an old next_match that we didn't preserve, handle cleanup
    if old_next_id and old_next_id != match.next_match:
        old_next_match = Match.query.filter_by(uuid=old_next_id, event=tournament_url).first()
        if old_next_match and old_next_match.previous_match == match.uuid:
            # This match's old next_match no longer has this match as its previous
            old_next_match.previous_match = None


# Register submodule handlers by importing them.
# This MUST be at the bottom so that bp and executor are already defined
# when submodules import them via `from . import bp`.
from app.routes.tournaments import (  # noqa: E402, F401
    brackets,
    management,
    matches_admin,
    read,
    recordings,
    scheduling,
)
