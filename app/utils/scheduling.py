"""
Utility functions for dynamic match scheduling.
"""
import json
from datetime import datetime, timedelta, timezone
from models import Match, db


def update_dynamic_schedule_after_completion(tournament_url: str, completed_match: Match) -> None:
    """When a match ends, pull forward subsequent dynamic matches on the same field until
    (but not including) the next static (dynamic == False) match.

    - Do NOT modify the immediately next match's scheduled time; only mark it ready to start.
    - For the match after next and onward (until a static boundary), set confirmed_start_time
      back-to-back based on prior matches' nominal_length.
    """
    try:
        if not completed_match.field:
            return
        # Ordered by nominal schedule to determine sequence
        field_matches = Match.query.filter_by(event=tournament_url, field=completed_match.field) \
            .order_by(Match.nominal_start_time.asc()) \
            .all()

        # Locate the completed match within the field sequence
        index_map = {m.uuid: i for i, m in enumerate(field_matches)}
        if completed_match.uuid not in index_map:
            return
        idx = index_map[completed_match.uuid]
        subsequent = field_matches[idx + 1:]
        if not subsequent:
            return

        # Stop at next static match (dynamic == False), not including it
        dynamic_chain = []
        for m in subsequent:
            if m.dynamic is False:
                break
            dynamic_chain.append(m)

        if not dynamic_chain:
            return

        # Use the finalization time as end-of-current-match
        end_ts = datetime.now(timezone.utc)

        # 1) Immediately next match: mark ready_to_start, keep scheduled time unchanged
        next_match = dynamic_chain[0]
        try:
            gs = json.loads(next_match.gamestate) if next_match.gamestate else {}
        except Exception:
            gs = {}
        gs['ready_to_start'] = True
        gs['ready_marked_at'] = end_ts.isoformat()
        gs['pulled_forward_from'] = completed_match.uuid
        next_match.gamestate = json.dumps(gs)

        # 2) Subsequent matches: set confirmed_start_time back-to-back,
        # constrained by dependency completion times

        default_minutes = 60

        def parse_iso(dt_str: str):
            if not dt_str:
                return None
            try:
                # Ensure timezone-aware parsing; fallback to UTC if naive
                d = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
                if d.tzinfo is None:
                    d = d.replace(tzinfo=timezone.utc)
                return d
            except Exception:
                return None

        def get_finalized_at(m: Match):
            try:
                gs = json.loads(m.gamestate) if m.gamestate else {}
                return parse_iso(gs.get('finalized_at'))
            except Exception:
                return None

        def referenced_match_ids(m: Match):
            """Return a set of match UUIDs this match depends on based on team1_initial/team2_initial.
            Supports references like 'Some Match winner', 'Some Match loser', or '<uuid> winner/loser'."""
            refs = set()
            def add_ref_from_initial(initial_val: str):
                if not initial_val:
                    return
                s = (initial_val or '').strip()
                s_low = ' '.join(s.lower().split())
                if s_low.endswith(' winner') or s_low.endswith(' loser'):
                    base = s.rsplit(' ', 1)[0]
                    # Try by UUID first
                    cand = Match.query.filter_by(event=tournament_url, uuid=base).first()
                    if cand:
                        refs.add(cand.uuid)
                        return
                    # Then by name
                    cand = Match.query.filter_by(event=tournament_url, name=base).first()
                    if cand:
                        refs.add(cand.uuid)
                        return
            add_ref_from_initial(m.team1_initial)
            add_ref_from_initial(m.team2_initial)
            return refs

        # Start pointer at end_ts + next_match.nominal_length, but do not set next_match time
        pointer = end_ts + timedelta(minutes=(next_match.nominal_length or default_minutes))

        for m in dynamic_chain[1:]:
            # Compute dependency readiness
            dep_ids = referenced_match_ids(m)
            deps_ready_at = None
            if dep_ids:
                dep_final_times = []
                for did in dep_ids:
                    dm = next((x for x in field_matches if x.uuid == did), None)
                    if dm:
                        ft = get_finalized_at(dm)
                        if ft:
                            dep_final_times.append(ft)
                if dep_final_times:
                    deps_ready_at = max(dep_final_times)

            # We can only pull forward to the later of pointer or dependencies readiness
            effective_start = pointer
            if deps_ready_at and deps_ready_at > effective_start:
                effective_start = deps_ready_at

            # If we cannot determine dependency completion (deps_ready_at is None) but this match
            # still references unresolved dependencies, do not move it earlier than its existing time.
            if dep_ids and deps_ready_at is None:
                existing = m.confirmed_start_time or m.nominal_start_time
                if existing:
                    # Normalize to timezone-aware for comparison
                    if existing.tzinfo is None:
                        existing = existing.replace(tzinfo=timezone.utc)
                    if effective_start < existing:
                        effective_start = existing

            m.confirmed_start_time = effective_start

            # Advance pointer by this match's nominal length from effective_start
            minutes = m.nominal_length or default_minutes
            pointer = effective_start + timedelta(minutes=minutes)

        db.session.commit()
    except Exception as e:
        # Log but don't raise to avoid breaking finalization
        print(f"update_dynamic_schedule_after_completion error on field {completed_match.field}: {e}")

