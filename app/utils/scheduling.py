"""
Utility functions for dynamic match scheduling.
"""
import json
from datetime import datetime, timedelta, timezone
from models import Match, db


def referenced_match_ids(match: Match, tournament_url: str) -> set:
    """Return a set of match UUIDs this match depends on based on team1_initial/team2_initial/refs_initial.
    Supports references like 'Some Match winner', 'Some Match loser', or '<uuid> winner/loser'.
    Also handles comma-separated values in refs_initial."""
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
    
    add_ref_from_initial(match.team1_initial)
    add_ref_from_initial(match.team2_initial)
    
    # Handle refs_initial which may contain comma-separated values
    if match.refs_initial:
        for ref_text in match.refs_initial.split(','):
            add_ref_from_initial(ref_text.strip())
    
    return refs


def compute_dynamic_match_nominal_start_time(match: Match, tournament_url: str) -> datetime | None:
    """Compute nominal_start_time for a dynamic match based on previous_match and referenced matches.
    
    For JOIN matches, also considers dependencies of all other joins with the same name.
    
    Returns the latest predicted end time among:
    - The previous_match (if set)
    - All matches referenced in team1_initial, team2_initial, or refs_initial
    - For JOIN matches: dependencies of all joins with the same name
    
    If no previous_match or referenced matches exist, returns None.
    """
    end_times = []
    
    # Special handling for JOIN matches: must consider all joins with the same name
    if match.type == 'JOIN':
        # Find all joins with the same name
        all_joins = Match.query.filter_by(
            event=tournament_url,
            type='JOIN',
            name=match.name
        ).all()
        
        # Collect dependencies from all joins with this name
        for join_match in all_joins:
            # Check previous_match for each join
            if join_match.previous_match:
                prev_match = Match.query.filter_by(uuid=join_match.previous_match, event=tournament_url).first()
                if prev_match and prev_match.nominal_start_time:
                    start_time = prev_match.nominal_start_time
                    if start_time.tzinfo is None:
                        start_time = start_time.replace(tzinfo=timezone.utc)
                    # JOIN matches have zero length
                    if prev_match.type == 'JOIN':
                        length_minutes = 0
                    else:
                        length_minutes = (prev_match.nominal_length or 60)
                    end_time = start_time + timedelta(minutes=length_minutes)
                    end_times.append(end_time)
            
            # Check referenced matches for each join
            ref_match_ids = referenced_match_ids(join_match, tournament_url)
            if ref_match_ids:
                ref_matches = Match.query.filter(
                    Match.uuid.in_(ref_match_ids),
                    Match.event == tournament_url
                ).all()
                
                for ref_match in ref_matches:
                    if ref_match.nominal_start_time:
                        start_time = ref_match.nominal_start_time
                        if start_time.tzinfo is None:
                            start_time = start_time.replace(tzinfo=timezone.utc)
                        # JOIN matches have zero length
                        if ref_match.type == 'JOIN':
                            length_minutes = 0
                        else:
                            length_minutes = (ref_match.nominal_length or 60)
                        end_time = start_time + timedelta(minutes=length_minutes)
                        end_times.append(end_time)
    else:
        # Regular match: only check its own dependencies
        # Check previous_match
        if match.previous_match:
            prev_match = Match.query.filter_by(uuid=match.previous_match, event=tournament_url).first()
            if prev_match and prev_match.nominal_start_time:
                start_time = prev_match.nominal_start_time
                if start_time.tzinfo is None:
                    start_time = start_time.replace(tzinfo=timezone.utc)
                # JOIN matches have zero length
                if prev_match.type == 'JOIN':
                    length_minutes = 0
                else:
                    length_minutes = (prev_match.nominal_length or 60)
                end_time = start_time + timedelta(minutes=length_minutes)
                end_times.append(end_time)
        
        # Check referenced matches from team1_initial, team2_initial, refs_initial
        ref_match_ids = referenced_match_ids(match, tournament_url)
        if ref_match_ids:
            ref_matches = Match.query.filter(
                Match.uuid.in_(ref_match_ids),
                Match.event == tournament_url
            ).all()
            
            for ref_match in ref_matches:
                if ref_match.nominal_start_time:
                    start_time = ref_match.nominal_start_time
                    if start_time.tzinfo is None:
                        start_time = start_time.replace(tzinfo=timezone.utc)
                    end_time = start_time + timedelta(minutes=(ref_match.nominal_length or 60))
                    end_times.append(end_time)
    
    if not end_times:
        return None
    
    # Return the latest end time as timezone-naive datetime
    latest_end_time = max(end_times)
    if latest_end_time.tzinfo is not None:
        latest_end_time = latest_end_time.replace(tzinfo=None)
    
    return latest_end_time


def update_match_sequence(match: Match, tournament_url: str) -> None:
    """Update previous_match and next_match relationships for matches on the same field.
    
    For static matches: orders by nominal_start_time
    For dynamic matches: uses previous_match relationship set by user
    """
    if not match.field:
        return
    
    # Get all matches on the same field (excluding the current match if it's being updated)
    field_matches = Match.query.filter_by(event=tournament_url, field=match.field).all()
    
    # Separate static and dynamic matches
    static_matches = [m for m in field_matches if not m.dynamic and m.nominal_start_time]
    dynamic_matches = [m for m in field_matches if m.dynamic]
    
    # Sort static matches by nominal_start_time
    static_matches.sort(key=lambda m: m.nominal_start_time)
    
    # Ensure static matches have no previous match
    for i, m in enumerate(static_matches):
        m.previous_match = None
        # Leave next_match unchanged here (do not auto-link static chain)
    
    # For dynamic matches, build chain based on previous_match relationships
    # Update next_match for each dynamic match
    for m in dynamic_matches:
        # Find the match that has this match as its previous_match
        next_m = next((dm for dm in dynamic_matches if dm.previous_match == m.uuid), None)
        m.next_match = next_m.uuid if next_m else None
    
    # Connect static chain to dynamic chain if they exist
    if static_matches and dynamic_matches:
        last_static = static_matches[-1]
        # Find first dynamic match (no previous_match or previous_match is last static)
        first_dynamic = next((dm for dm in dynamic_matches if not dm.previous_match or dm.previous_match == last_static.uuid), None)
        if first_dynamic and not first_dynamic.previous_match:
            # Connect: last static -> first dynamic
            last_static.next_match = first_dynamic.uuid
            first_dynamic.previous_match = last_static.uuid
        elif first_dynamic and first_dynamic.previous_match == last_static.uuid:
            last_static.next_match = first_dynamic.uuid


def recompute_all_match_times(tournament_url: str) -> None:
    """Recompute nominal_start_time for all dynamic matches in the tournament.
    This ensures that when one match is updated, all dependent matches are updated too.
    For JOIN matches with the same name, all must start at the same time.
    """
    # Get all matches ordered to process dependencies correctly
    all_matches = Match.query.filter_by(event=tournament_url).all()
    
    # Process dynamic matches in dependency order
    # We'll iterate multiple times until no more changes occur
    max_iterations = len(all_matches) * 2  # Safety limit
    changed = True
    iteration = 0
    
    while changed and iteration < max_iterations:
        changed = False
        iteration += 1
        
        for match in all_matches:
            if match.dynamic:
                old_start = match.nominal_start_time
                new_start = compute_dynamic_match_nominal_start_time(match, tournament_url)
                
                if new_start != old_start:
                    # Do not move earlier than a confirmed/locked start
                    if match.confirmed_start_time and new_start and new_start < match.confirmed_start_time:
                        match.nominal_start_time = match.confirmed_start_time
                    else:
                        match.nominal_start_time = new_start
                    changed = True
        
        if changed:
            db.session.flush()  # Ensure changes are visible for next iteration
        
        # For JOIN matches: synchronize all joins with the same name
        # Group JOIN matches by name and set all to the latest computed time
        join_groups: dict[str, list[Match]] = {}
        for match in all_matches:
            if match.type == 'JOIN' and match.dynamic:
                if match.name not in join_groups:
                    join_groups[match.name] = []
                join_groups[match.name].append(match)
        
        # For each group, set all to the latest start time
        for join_name, join_matches in join_groups.items():
            if len(join_matches) > 1:
                # Find the latest start time among all joins with this name
                start_times = [m.nominal_start_time for m in join_matches if m.nominal_start_time]
                if start_times:
                    latest_start = max(start_times)
                    # Set all joins to this time
                    for join_match in join_matches:
                        if join_match.nominal_start_time != latest_start:
                            # Do not move earlier than confirmed for joins either
                            if join_match.confirmed_start_time and latest_start and latest_start < join_match.confirmed_start_time:
                                join_match.nominal_start_time = join_match.confirmed_start_time
                            else:
                                join_match.nominal_start_time = latest_start
                            changed = True
        
        if changed:
            db.session.flush()
    
    # Update sequence relationships for all fields
    for match in all_matches:
        if match.field:
            update_match_sequence(match, tournament_url)
    
    db.session.flush()


def detect_circular_dependencies(tournament_url: str) -> dict[str, list[str]]:
    """Detect circular dependencies in match scheduling.
    
    Returns a dictionary mapping match UUIDs to lists of error messages describing circular dependencies.
    Uses DFS to detect cycles in the dependency graph.
    """
    matches = Match.query.filter_by(event=tournament_url).all()
    match_dict = {m.uuid: m for m in matches}
    
    # Build dependency graph: match_uuid -> set of match_uuids it depends on
    dependencies: dict[str, set[str]] = {}
    
    for match in matches:
        deps = set()
        
        # Add previous_match dependency
        if match.previous_match:
            deps.add(match.previous_match)
        
        # Add referenced matches from team1_initial, team2_initial, refs_initial
        ref_match_ids = referenced_match_ids(match, tournament_url)
        deps.update(ref_match_ids)
        
        dependencies[match.uuid] = deps
    
    # DFS to detect cycles
    def find_cycles() -> dict[str, list[str]]:
        """Find all cycles in the dependency graph."""
        cycles: dict[str, list[str]] = {}
        visited: set[str] = set()
        rec_stack: set[str] = set()
        path: list[str] = []
        cycle_paths: set[tuple[str, ...]] = set()  # Track unique cycles to avoid duplicates
        
        def dfs(node: str) -> None:
            """DFS to detect cycles."""
            if node in rec_stack:
                # Found a cycle - extract the cycle path
                cycle_start = path.index(node)
                cycle = tuple(path[cycle_start:] + [node])
                
                # Avoid reporting the same cycle multiple times
                if cycle in cycle_paths:
                    return
                
                cycle_paths.add(cycle)
                
                # Add error to all matches in the cycle
                cycle_matches = [match_dict[uuid].name for uuid in cycle if uuid in match_dict]
                cycle_str = " -> ".join(cycle_matches)
                
                for uuid in cycle:
                    if uuid in match_dict:
                        if uuid not in cycles:
                            cycles[uuid] = []
                        cycles[uuid].append(f"Circular dependency detected: {cycle_str}")
                
                return
            
            if node in visited:
                return
            
            visited.add(node)
            rec_stack.add(node)
            path.append(node)
            
            # Visit all dependencies
            for dep in dependencies.get(node, set()):
                if dep in match_dict:  # Only check if dependency exists
                    dfs(dep)
            
            path.pop()
            rec_stack.remove(node)
        
        # Check each match for cycles
        for match_uuid in dependencies:
            if match_uuid not in visited:
                dfs(match_uuid)
        
        return cycles
    
    return find_cycles()


def detect_match_conflicts(tournament_url: str) -> dict[str, list[str]]:
    """Detect conflicts across all matches and return a dict mapping match UUID to list of error messages.
    
    Returns a dictionary where keys are match UUIDs and values are lists of conflict error messages.
    Includes circular dependency detection.
    """
    conflicts: dict[str, list[str]] = {}
    
    # First, check for circular dependencies
    circular_deps = detect_circular_dependencies(tournament_url)
    for match_uuid, errors in circular_deps.items():
        if match_uuid not in conflicts:
            conflicts[match_uuid] = []
        conflicts[match_uuid].extend(errors)
    
    matches = Match.query.filter_by(event=tournament_url).all()
    
    for match in matches:
        match_errors = []
        
        if not match.nominal_start_time:
            continue
        
        this_start = match.nominal_start_time
        # JOIN matches have zero length
        if match.type == 'JOIN':
            this_length_minutes = 0
        else:
            this_length_minutes = (match.nominal_length or 60)
        this_end = this_start + timedelta(minutes=this_length_minutes)
        
        # Collect all teams/refs for this match
        this_teams = set()
        if match.team1:
            this_teams.add(match.team1)
        if match.team2:
            this_teams.add(match.team2)
        if match.refs:
            this_teams.update(m.strip() for m in match.refs.split(',') if m.strip())
        
        # Also check initial fields for team references
        this_initials = set(_initial_tokens(match.team1_initial or ''))
        this_initials.update(_initial_tokens(match.team2_initial or ''))
        this_initials.update(_initial_tokens(match.refs_initial or ''))
        
        # Check against all other matches
        for other in matches:
            if other.uuid == match.uuid:
                continue
            
            if not other.nominal_start_time:
                continue
            
            other_start = other.nominal_start_time
            # JOIN matches have zero length
            if other.type == 'JOIN':
                other_length_minutes = 0
            else:
                other_length_minutes = (other.nominal_length or 60)
            other_end = other_start + timedelta(minutes=other_length_minutes)
            
            # Check for field overlap
            if match.field and other.field == match.field:
                # Check if time intervals overlap: [this_start, this_end) and [other_start, other_end)
                if this_start < other_end and other_start < this_end:
                    match_errors.append(f"Overlaps on field '{match.field}' with match '{other.name}' ({other_start.strftime('%Y-%m-%d %H:%M')})")
            
            # Check for team double-booking
            other_teams = set()
            if other.team1:
                other_teams.add(other.team1)
            if other.team2:
                other_teams.add(other.team2)
            if other.refs:
                other_teams.update(m.strip() for m in other.refs.split(',') if m.strip())
            
            other_initials = set(_initial_tokens(other.team1_initial or ''))
            other_initials.update(_initial_tokens(other.team2_initial or ''))
            other_initials.update(_initial_tokens(other.refs_initial or ''))
            
            # Check if time intervals overlap
            if this_start < other_end and other_start < this_end:
                # Check for team conflicts
                team_conflict = this_teams & other_teams
                if team_conflict:
                    match_errors.append(f"Team(s) {', '.join(team_conflict)} double-booked with match '{other.name}'")
                
                # Check for initial field conflicts (team names/references)
                initial_conflict = this_initials & other_initials
                if initial_conflict:
                    match_errors.append(f"Team/ref '{', '.join(initial_conflict)}' double-booked with match '{other.name}'")
        
        if match_errors:
            conflicts[match.uuid] = match_errors
    
    return conflicts


def _predicted_end_time(m: Match) -> datetime | None:
    """Return predicted end time using nominal_start_time + nominal_length."""
    if not m or not m.nominal_start_time:
        return None
    start_time = m.nominal_start_time
    # JOIN matches have zero length
    if m.type == 'JOIN':
        length_minutes = 0
    else:
        length_minutes = (m.nominal_length or 60)
    return start_time + timedelta(minutes=length_minutes)


def _extract_refs_from_text(text: str) -> list[tuple[str, str]]:
    """Extract (base, kind) pairs from a free text that may contain '... winner' or '... loser'."""
    refs: list[tuple[str, str]] = []
    if not text:
        return refs
    # Split by commas to catch multiple refs in refs_initial
    parts = [p.strip() for p in text.split(',') if p.strip()]
    for p in parts:
        low = ' '.join(p.lower().split())
        if low.endswith(' winner'):
            base = p.rsplit(' ', 1)[0].strip()
            refs.append((base, 'winner'))
        elif low.endswith(' loser'):
            base = p.rsplit(' ', 1)[0].strip()
            refs.append((base, 'loser'))
    return refs

def _initial_tokens(text: str) -> list[str]:
    """Split an *_initial field by commas into simple tokens (trimmed, non-empty)."""
    if not text:
        return []
    return [p.strip() for p in text.split(',') if p.strip()]


def resolve_reference_to_match(base: str, tournament_url: str) -> Match | None:
    """Resolve a reference base string to a Match by UUID first, then by name."""
    # UUID match
    cand = Match.query.filter_by(event=tournament_url, uuid=base).first()
    if cand:
        return cand
    # Name match
    cand = Match.query.filter_by(event=tournament_url, name=base).first()
    return cand


def validate_match_input(match: Match, tournament_url: str) -> tuple[bool, str | None]:
    """Validate match logical constraints.
    - Disallow self-references (winner/loser of current match as team/ref of itself)
    - Only reference matches that end before this match starts
    - BREAK and JOIN matches don't require teams/refs
    Note: Overlaps and double-booking are now detected but don't block saves - see detect_match_conflicts()
    Returns (ok, error_message)
    """
    # BREAK and JOIN matches don't need start time validation for teams/refs
    if match.type in ('BREAK', 'JOIN'):
        # For JOIN matches, ensure length is 0
        if match.type == 'JOIN' and match.nominal_length and match.nominal_length != 0:
            return False, "JOIN matches must have zero length."
        return True, None
    
    # For standard matches, require number of sets
    if match.nsets is None or int(match.nsets) <= 0:
        return False, "Number of sets is required and must be > 0 for non-BREAK/JOIN matches."

    # Determine this match nominal start
    this_start = match.nominal_start_time
    if not this_start:
        return False, "Match start time could not be determined."

    # Collect references from team initials and refs_initial
    ref_tuples: list[tuple[str, str]] = []
    ref_tuples += _extract_refs_from_text(match.team1_initial or '')
    ref_tuples += _extract_refs_from_text(match.team2_initial or '')
    ref_tuples += _extract_refs_from_text(match.refs_initial or '')

    # Resolve and check each reference
    for base, kind in ref_tuples:
        ref_match = resolve_reference_to_match(base, tournament_url)
        if not ref_match:
            # If the user typed a result reference, base must resolve
            return False, f"Referenced match '{base}' was not found."
        # Self-reference is not allowed
        if match.uuid and ref_match.uuid == match.uuid:
            return False, "A match cannot reference its own winner/loser for teams or refs."
        # Dependency must end before this match starts
        ref_end = _predicted_end_time(ref_match)
        if not ref_end:
            return False, f"Referenced match '{ref_match.name}' has no start time set."
        # Normalize naive vs aware by treating values as naive consistently
        if ref_end > this_start:
            return False, (
                f"Referenced match '{ref_match.name}' is scheduled to end after this match starts."
            )

    # Note: Overlap and double-booking checks removed - these are now handled by detect_match_conflicts()
    # and shown as warnings rather than blocking saves

    return True, None


def get_match_dependencies(match: Match, tournament_url: str) -> list[Match]:
    """Get all matches that this match depends on (previous_match + referenced matches)."""
    deps = []
    
    # Add previous_match if it exists
    if match.previous_match:
        prev_match = Match.query.filter_by(uuid=match.previous_match, event=tournament_url).first()
        if prev_match:
            deps.append(prev_match)
    
    # Add referenced matches from team1_initial, team2_initial, refs_initial
    ref_match_ids = referenced_match_ids(match, tournament_url)
    if ref_match_ids:
        ref_matches = Match.query.filter(
            Match.uuid.in_(ref_match_ids),
            Match.event == tournament_url
        ).all()
        deps.extend(ref_matches)
    
    return deps


def get_last_dependency_start_time(match: Match, tournament_url: str) -> datetime | None:
    """Get the start time of the last dependency that needs to start before this match can be finalized.
    Returns None if no dependencies or none have started."""
    deps = get_match_dependencies(match, tournament_url)
    if not deps:
        return None
    
    start_times = []
    for dep in deps:
        # Check confirmed_start_time first (actual start), then nominal_start_time
        start_time = dep.confirmed_start_time or dep.nominal_start_time
        if start_time:
            if start_time.tzinfo is None:
                start_time = start_time.replace(tzinfo=timezone.utc)
            start_times.append(start_time)
    
    return max(start_times) if start_times else None


def get_last_dependency_end_time(match: Match, tournament_url: str) -> datetime | None:
    """Get the end time of the last dependency that needs to finish before this match can start.
    Returns None if no dependencies or none have finished."""
    deps = get_match_dependencies(match, tournament_url)
    if not deps:
        return None
    
    def parse_iso(dt_str: str):
        if not dt_str:
            return None
        try:
            d = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            return d
        except Exception:
            return None
    
    def get_finalized_at(m: Match):
        # Prefer dedicated column if present
        if getattr(m, 'completed_time', None):
            d = m.completed_time
            try:
                if d and d.tzinfo is None:
                    d = d.replace(tzinfo=timezone.utc)
            except Exception:
                pass
            return d
        if m.status == 'COMPLETED':
            try:
                gs = json.loads(m.gamestate) if m.gamestate else {}
                finalized_str = gs.get('finalized_at')
                if finalized_str:
                    return parse_iso(finalized_str)
            except Exception:
                pass
        return None
    
    end_times = []
    for dep in deps:
        # Use finalized_at if available, otherwise compute from start + length
        end_time = get_finalized_at(dep)
        if not end_time:
            # Fallback to predicted end time
            start_time = dep.confirmed_start_time or dep.nominal_start_time
            if start_time:
                if start_time.tzinfo is None:
                    start_time = start_time.replace(tzinfo=timezone.utc)
                end_time = start_time + timedelta(minutes=(dep.nominal_length or 60))
        if end_time:
            end_times.append(end_time)
    
    return max(end_times) if end_times else None


def mark_dependent_matches_time_finalized(started_match: Match, tournament_url: str) -> None:
    """When a match starts, mark all dependent matches as having their time finalized.
    The time is finalized when the last dependency starts, at which point the start time
    can be computed based on the duration of the dependent match."""
    # Find all matches that depend on this match
    all_matches = Match.query.filter_by(event=tournament_url).all()
    
    for match in all_matches:
        if match.status in ('IN_PROGRESS', 'COMPLETED'):
            continue  # Already started or completed
        
        deps = get_match_dependencies(match, tournament_url)
        if not deps:
            continue
        
        # Check if this match is a dependency
        if started_match.uuid not in [d.uuid for d in deps]:
            continue
        
        # Check if all dependencies have now started
        all_deps_started = all(
            dep.status == 'IN_PROGRESS' or dep.status == 'COMPLETED' or dep.confirmed_start_time
            for dep in deps
        )
        
        if all_deps_started:
            # Special handling for JOIN: finalize as a group across same-name joins
            if match.type == 'JOIN':
                join_group = Match.query.filter_by(event=tournament_url, type='JOIN', name=match.name).all()
                # Check that all joins in the group have all dependencies started
                group_ready = True
                group_finalized_candidates = []
                for jm in join_group:
                    jm_deps = get_match_dependencies(jm, tournament_url)
                    if not jm_deps:
                        group_ready = False
                        break
                    jm_all_started = all(
                        d.status in ('IN_PROGRESS', 'COMPLETED') or d.confirmed_start_time
                        for d in jm_deps
                    )
                    if not jm_all_started:
                        group_ready = False
                        break
                    # Compute this join's finalized start candidate
                    jm_last_start = get_last_dependency_start_time(jm, tournament_url)
                    if jm_last_start is None:
                        group_ready = False
                        break
                    # Find dependency with that last start to get its duration
                    jm_last_dep = None
                    for d in jm_deps:
                        ds = d.confirmed_start_time or d.nominal_start_time
                        if ds:
                            if ds.tzinfo is None:
                                ds = ds.replace(tzinfo=timezone.utc)
                            if ds == jm_last_start:
                                jm_last_dep = d
                                break
                    if jm_last_dep is None:
                        group_ready = False
                        break
                    # JOIN matches have zero length
                    if jm_last_dep.type == 'JOIN':
                        dep_length_minutes = 0
                    else:
                        dep_length_minutes = (jm_last_dep.nominal_length or 60)
                    jm_finalized = jm_last_start + timedelta(minutes=dep_length_minutes)
                    group_finalized_candidates.append(jm_finalized)
                if group_ready and group_finalized_candidates:
                    group_finalized_start = max(group_finalized_candidates)
                    for jm in join_group:
                        try:
                            gs = json.loads(jm.gamestate) if jm.gamestate else {}
                        except Exception:
                            gs = {}
                        gs['time_finalized'] = True
                        gs['time_finalized_at'] = datetime.now(timezone.utc).isoformat()
                        gs['finalized_start_time'] = group_finalized_start.isoformat()
                        jm.gamestate = json.dumps(gs)
                # If group not ready, do nothing for JOIN yet
                continue

            # Non-JOIN behavior: finalize individually
            # Compute finalized start time based on the last dependency's start + duration
            last_dep_start = get_last_dependency_start_time(match, tournament_url)
            if last_dep_start:
                # Find the dependency that started last
                last_dep = None
                for dep in deps:
                    dep_start = dep.confirmed_start_time or dep.nominal_start_time
                    if dep_start:
                        if dep_start.tzinfo is None:
                            dep_start = dep_start.replace(tzinfo=timezone.utc)
                        if dep_start == last_dep_start:
                            last_dep = dep
                            break
                
                if last_dep:
                    # Compute finalized start time: last dependency start + its duration
                    # JOIN matches have zero length
                    if last_dep.type == 'JOIN':
                        dep_length_minutes = 0
                    else:
                        dep_length_minutes = (last_dep.nominal_length or 60)
                    finalized_start = last_dep_start + timedelta(minutes=dep_length_minutes)
                    
                    # Update gamestate (do not set confirmed_start_time here)
                    try:
                        gs = json.loads(match.gamestate) if match.gamestate else {}
                    except Exception:
                        gs = {}
                    gs['time_finalized'] = True
                    gs['time_finalized_at'] = datetime.now(timezone.utc).isoformat()
                    gs['finalized_start_time'] = finalized_start.isoformat()
                    match.gamestate = json.dumps(gs)


def mark_dependent_matches_ready_to_start(completed_match: Match, tournament_url: str) -> None:
    """When a match finishes, mark all dependent matches as ready to start.
    A match is ready to start when the last dependency finishes."""
    # Find all matches that depend on this match
    all_matches = Match.query.filter_by(event=tournament_url).all()
    
    for match in all_matches:
        if match.status in ('IN_PROGRESS', 'COMPLETED'):
            continue  # Already started or completed
        
        deps = get_match_dependencies(match, tournament_url)
        if not deps:
            continue
        
        # Check if this match is a dependency
        if completed_match.uuid not in [d.uuid for d in deps]:
            continue
        
        # Check if all dependencies have now finished
        all_deps_finished = all(dep.status == 'COMPLETED' for dep in deps)
        
        if all_deps_finished:
            # Update gamestate (no confirmed_start_time here)
            try:
                gs = json.loads(match.gamestate) if match.gamestate else {}
            except Exception:
                gs = {}
            gs['ready_to_start'] = True
            gs['ready_to_start_at'] = datetime.now(timezone.utc).isoformat()
            
            # If not already time_finalized, compute and set now (fallback)
            if not gs.get('time_finalized'):
                last_dep_start = get_last_dependency_start_time(match, tournament_url)
                if last_dep_start:
                    # Identify the last-starting dependency to get its duration
                    deps2 = get_match_dependencies(match, tournament_url)
                    last_dep = None
                    for dep in deps2:
                        dep_start = dep.confirmed_start_time or dep.nominal_start_time
                        if dep_start:
                            if dep_start.tzinfo is None:
                                dep_start = dep_start.replace(tzinfo=timezone.utc)
                            if dep_start == last_dep_start:
                                last_dep = dep
                                break
                    if last_dep:
                        # JOIN matches have zero length
                        if last_dep.type == 'JOIN':
                            dep_length_minutes = 0
                        else:
                            dep_length_minutes = (last_dep.nominal_length or 60)
                        finalized_start = last_dep_start + timedelta(minutes=dep_length_minutes)
                        gs['time_finalized'] = True
                        gs['time_finalized_at'] = datetime.now(timezone.utc).isoformat()
                        gs['finalized_start_time'] = finalized_start.isoformat()
            
            match.gamestate = json.dumps(gs)


def auto_complete_break_match(completed_match: Match, tournament_url: str) -> None:
    """If a finalized match's successor is a BREAK match, automatically mark it complete.
    The break's end time is computed as start time + length."""
    if not completed_match.next_match:
        return
    
    next_match = Match.query.filter_by(uuid=completed_match.next_match, event=tournament_url).first()
    if not next_match or next_match.type != 'BREAK':
        return
    
    if next_match.status != 'NOT_STARTED':
        return  # Already started or completed
    
    # Compute break start time (end of completed match)
    def parse_iso(dt_str: str):
        if not dt_str:
            return None
        try:
            d = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            return d
        except Exception:
            return None
    
    def get_finalized_at(m: Match):
        if m.status == 'COMPLETED':
            try:
                gs = json.loads(m.gamestate) if m.gamestate else {}
                finalized_str = gs.get('finalized_at')
                if finalized_str:
                    return parse_iso(finalized_str)
            except Exception:
                pass
        return None
    
    completed_end = get_finalized_at(completed_match)
    if not completed_end:
        # Fallback: use current time
        completed_end = datetime.now(timezone.utc)
    
    # Break starts when previous match ends
    break_start = completed_end
    if break_start.tzinfo is None:
        break_start = break_start.replace(tzinfo=timezone.utc)
    
    # Break ends at start + length
    # JOIN matches have zero length
    if next_match.type == 'JOIN':
        break_length_minutes = 0
    else:
        break_length_minutes = next_match.nominal_length or 60
    break_end = break_start + timedelta(minutes=break_length_minutes)
    
    # Mark break as completed
    next_match.status = 'COMPLETED'
    if break_start.tzinfo is not None:
        break_start = break_start.replace(tzinfo=None)
    next_match.confirmed_start_time = break_start
    # Record completion time
    if break_end.tzinfo is not None:
        next_match.completed_time = break_end.replace(tzinfo=None)
    else:
        next_match.completed_time = break_end
    
    # Set gamestate
    gamestate = {
        'finalized_at': break_end.isoformat(),
        'finalized_by': 'system',
        'auto_completed': True,
        'start_time': break_start.isoformat(),
        'end_time': break_end.isoformat()
    }
    next_match.gamestate = json.dumps(gamestate)
    
    # Commit and recursively process any dependent matches
    db.session.commit()
    
    # The break's start is now known; finalize dependent starts and mark readiness
    try:
        mark_dependent_matches_time_finalized(next_match, tournament_url)
        mark_dependent_matches_ready_to_start(next_match, tournament_url)
    except Exception as e:
        print(f"Error propagating from break {next_match.name}: {e}")
    
    # Recursively handle any matches that depend on this break
    try:
        auto_complete_break_match(next_match, tournament_url)
        auto_complete_join_matches(tournament_url)
    except Exception as e:
        print(f"Error in recursive break completion: {e}")


def auto_complete_join_matches(tournament_url: str) -> None:
    """For all JOIN matches, if the last dependency for all joins of the same name is completed,
    mark all of the joins completed and trigger their finalization steps."""
    # Group JOIN matches by name
    all_matches = Match.query.filter_by(event=tournament_url, type='JOIN').all()
    join_groups: dict[str, list[Match]] = {}
    
    for match in all_matches:
        if match.status != 'NOT_STARTED':
            continue  # Already started or completed
        if match.name not in join_groups:
            join_groups[match.name] = []
        join_groups[match.name].append(match)
    
    # For each group, check if all dependencies are complete
    for join_name, join_matches in join_groups.items():
        if not join_matches:
            continue
        
        # Collect all dependencies from all joins with this name
        all_deps: set[str] = set()
        for join_match in join_matches:
            deps = get_match_dependencies(join_match, tournament_url)
            all_deps.update(dep.uuid for dep in deps)
        
        if not all_deps:
            continue  # No dependencies
        
        # Check if all dependencies are completed
        all_deps_completed = True
        latest_end_time = None
        
        for dep_uuid in all_deps:
            dep_match = Match.query.filter_by(uuid=dep_uuid, event=tournament_url).first()
            if not dep_match or dep_match.status != 'COMPLETED':
                all_deps_completed = False
                break
            
            # Get end time
            def parse_iso(dt_str: str):
                if not dt_str:
                    return None
                try:
                    d = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
                    if d.tzinfo is None:
                        d = d.replace(tzinfo=timezone.utc)
                    return d
                except Exception:
                    return None
            
            def get_finalized_at(m: Match):
                if getattr(m, 'completed_time', None):
                    d = m.completed_time
                    try:
                        if d and d.tzinfo is None:
                            d = d.replace(tzinfo=timezone.utc)
                    except Exception:
                        pass
                    return d
                if m.status == 'COMPLETED':
                    try:
                        gs = json.loads(m.gamestate) if m.gamestate else {}
                        finalized_str = gs.get('finalized_at')
                        if finalized_str:
                            return parse_iso(finalized_str)
                    except Exception:
                        pass
                return None
            
            dep_end = get_finalized_at(dep_match)
            if not dep_end:
                # Fallback: compute from start + length
                start_time = dep_match.confirmed_start_time or dep_match.nominal_start_time
                if start_time:
                    if start_time.tzinfo is None:
                        start_time = start_time.replace(tzinfo=timezone.utc)
                    # JOIN matches have zero length
                    if dep_match.type == 'JOIN':
                        dep_length_minutes = 0
                    else:
                        dep_length_minutes = (dep_match.nominal_length or 60)
                    dep_end = start_time + timedelta(minutes=dep_length_minutes)
            
            if dep_end:
                if latest_end_time is None or dep_end > latest_end_time:
                    latest_end_time = dep_end
        
        if all_deps_completed and latest_end_time:
            # All joins with this name start at the same time (latest dependency end)
            join_start = latest_end_time
            if join_start.tzinfo is None:
                join_start = join_start.replace(tzinfo=timezone.utc)
            
            # JOIN matches have zero length, so end = start
            join_end = join_start
            
            # Mark all joins as completed
            for join_match in join_matches:
                join_match.status = 'COMPLETED'
                if join_start.tzinfo is not None:
                    join_start_naive = join_start.replace(tzinfo=None)
                else:
                    join_start_naive = join_start
                join_match.confirmed_start_time = join_start_naive
                # Record completion time (same as start for zero-length)
                join_match.completed_time = join_start_naive
                
                # Set gamestate
                gamestate = {
                    'finalized_at': join_end.isoformat(),
                    'finalized_by': 'system',
                    'auto_completed': True,
                    'start_time': join_start.isoformat(),
                    'end_time': join_end.isoformat()
                }
                join_match.gamestate = json.dumps(gamestate)
            
            # Commit the JOIN completions
            db.session.commit()
            
            # The joins' starts are now known; finalize dependent starts and mark readiness
            for join_match in join_matches:
                try:
                    mark_dependent_matches_time_finalized(join_match, tournament_url)
                    mark_dependent_matches_ready_to_start(join_match, tournament_url)
                except Exception as e:
                    print(f"Error propagating from join {join_match.name}: {e}")
        
        
        # Recursively check for any matches that depend on these joins
        for join_match in join_matches:
            if join_match.status == 'COMPLETED':
                try:
                    auto_complete_break_match(join_match, tournament_url)
                    auto_complete_join_matches(tournament_url)
                except Exception as e:
                    print(f"Error in recursive join completion: {e}")


def update_dynamic_schedule_after_completion(tournament_url: str, completed_match: Match) -> None:
    """When a match ends, update dependent matches and handle BREAK/JOIN auto-completion.

    - Mark dependent matches as ready to start
    - Auto-complete BREAK matches if they're the next match
    - Auto-complete JOIN matches if all dependencies are finished
    - Pull forward subsequent dynamic matches on the same field
    """
    try:
        # First, mark dependent matches as ready to start
        mark_dependent_matches_ready_to_start(completed_match, tournament_url)
        
        # Auto-complete BREAK matches
        auto_complete_break_match(completed_match, tournament_url)
        
        # Auto-complete JOIN matches
        auto_complete_join_matches(tournament_url)
        
        # Then handle field-based scheduling updates
        if not completed_match.field:
            db.session.commit()
            return
        
        # Ordered by nominal schedule to determine sequence
        field_matches = Match.query.filter_by(event=tournament_url, field=completed_match.field) \
            .order_by(Match.nominal_start_time.asc()) \
            .all()

        # Locate the completed match within the field sequence
        index_map = {m.uuid: i for i, m in enumerate(field_matches)}
        if completed_match.uuid not in index_map:
            db.session.commit()
            return
        idx = index_map[completed_match.uuid]
        subsequent = field_matches[idx + 1:]
        if not subsequent:
            db.session.commit()
            return

        # Stop at next static match (dynamic == False), not including it
        dynamic_chain = []
        for m in subsequent:
            if m.dynamic is False:
                break
            dynamic_chain.append(m)

        if not dynamic_chain:
            db.session.commit()
            return

        # Use the finalization time as end-of-current-match
        def parse_iso(dt_str: str):
            if not dt_str:
                return None
            try:
                d = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
                if d.tzinfo is None:
                    d = d.replace(tzinfo=timezone.utc)
                return d
            except Exception:
                return None

        def get_finalized_at(m: Match):
            if getattr(m, 'completed_time', None):
                d = m.completed_time
                try:
                    if d and d.tzinfo is None:
                        d = d.replace(tzinfo=timezone.utc)
                except Exception:
                    pass
                return d
            if m.status == 'COMPLETED':
                try:
                    gs = json.loads(m.gamestate) if m.gamestate else {}
                    finalized_str = gs.get('finalized_at')
                    if finalized_str:
                        return parse_iso(finalized_str)
                except Exception:
                    pass
            return None
        
        end_ts = get_finalized_at(completed_match)
        if not end_ts:
            end_ts = datetime.now(timezone.utc)

        # 1) Immediately next match: update predicted nominal start to the end of
        # the completed match (no finalization here). Readiness is handled elsewhere.
        next_match = dynamic_chain[0]
        try:
            if next_match.status == 'NOT_STARTED' and next_match.type not in ('BREAK', 'JOIN'):
                nm = end_ts
                # Store as naive for DB consistency
                if nm.tzinfo is not None:
                    nm = nm.replace(tzinfo=None)
                next_match.nominal_start_time = nm
        except Exception:
            pass

        # Helper to normalize to aware UTC
        def to_aware_utc(d):
            if not d:
                return None
            try:
                if d.tzinfo is None:
                    return d.replace(tzinfo=timezone.utc)
            except Exception:
                pass
            return d

        # 2) Subsequent matches: update predicted nominal_start_time back-to-back,
        # constrained by dependency completion times (do not finalize here)

        default_minutes = 60

        # Start pointer at end_ts + next_match.nominal_length, but do not set next_match time
        # JOIN matches have zero length, so use 0 for them
        if next_match.type == 'JOIN':
            next_match_length = 0
        else:
            next_match_length = (next_match.nominal_length or default_minutes)
        pointer = end_ts + timedelta(minutes=next_match_length)

        for m in dynamic_chain[1:]:
            if m.status in ('IN_PROGRESS', 'COMPLETED'):
                continue  # Skip matches that have already started or completed
            
            # Compute dependency readiness
            dep_ids = referenced_match_ids(m, tournament_url)
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
            deps_ready_at = to_aware_utc(deps_ready_at)
            effective_start = to_aware_utc(effective_start)
            if deps_ready_at and effective_start and deps_ready_at > effective_start:
                effective_start = deps_ready_at

            # If we cannot determine dependency completion (deps_ready_at is None) but this match
            # still references unresolved dependencies, do not move it earlier than its existing time.
            if dep_ids and deps_ready_at is None:
                existing = m.confirmed_start_time or m.nominal_start_time
                if existing:
                    # Normalize to timezone-aware for comparison
                    existing = to_aware_utc(existing)
                    # Ensure effective_start is aware as well
                    effective_start = to_aware_utc(effective_start)
                    if effective_start and existing and effective_start < existing:
                        effective_start = existing

            # Store as nominal prediction only; do not set confirmed here
            if effective_start.tzinfo is not None:
                effective_start = effective_start.replace(tzinfo=None)
            m.nominal_start_time = effective_start

            # Advance pointer by this match's nominal length from effective_start
            # JOIN matches have zero length
            if m.type == 'JOIN':
                minutes = 0
            else:
                minutes = m.nominal_length or default_minutes
            pointer = effective_start + timedelta(minutes=minutes)

        db.session.commit()
    except Exception as e:
        # Log but don't raise to avoid breaking finalization
        print(f"update_dynamic_schedule_after_completion error on field {completed_match.field}: {e}")
        db.session.rollback()

