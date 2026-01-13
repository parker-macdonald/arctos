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
        s = (initial_val or "").strip()
        base = None
        # Check for new format: match_name::winner or match_name::loser
        if "::winner" in s or s.endswith("::winner"):
            base = s.split("::")[0].strip()
        elif "::loser" in s or s.endswith("::loser"):
            base = s.split("::")[0].strip()
        # Legacy format: match_name winner or match_name loser
        else:
            s_low = " ".join(s.lower().split())
            if s_low.endswith(" winner") or s_low.endswith(" loser"):
                base = s.rsplit(" ", 1)[0]

        if base:
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
        for ref_text in match.refs_initial.split(","):
            add_ref_from_initial(ref_text.strip())

    return refs


def compute_dynamic_match_nominal_start_time(
    match: Match, tournament_url: str
) -> datetime | None:
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
    if match.schedule_type == "JOIN":
        # Find all joins with the same name
        all_joins = Match.query.filter_by(
            event=tournament_url, schedule_type="JOIN", name=match.name
        ).all()

        # Collect dependencies from all joins with this name
        for join_match in all_joins:
            # Check previous_match for each join
            if join_match.previous_match:
                prev_match = Match.query.filter_by(
                    uuid=join_match.previous_match, event=tournament_url
                ).first()
                if prev_match and prev_match.nominal_start_time:
                    start_time = prev_match.nominal_start_time
                    if start_time.tzinfo is None:
                        start_time = start_time.replace(tzinfo=timezone.utc)
                    # JOIN matches have zero length
                    if prev_match.schedule_type == "JOIN":
                        length_minutes = 0
                    else:
                        length_minutes = prev_match.nominal_length or 60
                    end_time = start_time + timedelta(minutes=length_minutes)
                    end_times.append(end_time)

            # Check referenced matches for each join
            ref_match_ids = referenced_match_ids(join_match, tournament_url)
            if ref_match_ids:
                ref_matches = Match.query.filter(
                    Match.uuid.in_(ref_match_ids), Match.event == tournament_url
                ).all()

                for ref_match in ref_matches:
                    if ref_match.nominal_start_time:
                        start_time = ref_match.nominal_start_time
                        if start_time.tzinfo is None:
                            start_time = start_time.replace(tzinfo=timezone.utc)
                        # JOIN matches have zero length
                        if ref_match.schedule_type == "JOIN":
                            length_minutes = 0
                        else:
                            length_minutes = ref_match.nominal_length or 60
                        end_time = start_time + timedelta(minutes=length_minutes)
                        end_times.append(end_time)
    else:
        # Regular match: only check its own dependencies
        # Check previous_match
        if match.previous_match:
            prev_match = Match.query.filter_by(
                uuid=match.previous_match, event=tournament_url
            ).first()
            if prev_match and prev_match.nominal_start_time:
                start_time = prev_match.nominal_start_time
                if start_time.tzinfo is None:
                    start_time = start_time.replace(tzinfo=timezone.utc)
                # JOIN matches have zero length
                if prev_match.schedule_type == "JOIN":
                    length_minutes = 0
                else:
                    length_minutes = prev_match.nominal_length or 60
                end_time = start_time + timedelta(minutes=length_minutes)
                end_times.append(end_time)

        # Check referenced matches from team1_initial, team2_initial, refs_initial
        ref_match_ids = referenced_match_ids(match, tournament_url)
        if ref_match_ids:
            ref_matches = Match.query.filter(
                Match.uuid.in_(ref_match_ids), Match.event == tournament_url
            ).all()

            for ref_match in ref_matches:
                if ref_match.nominal_start_time:
                    start_time = ref_match.nominal_start_time
                    if start_time.tzinfo is None:
                        start_time = start_time.replace(tzinfo=timezone.utc)
                    end_time = start_time + timedelta(
                        minutes=(ref_match.nominal_length or 60)
                    )
                    end_times.append(end_time)

    if not end_times:
        return None

    # Return the latest end time as timezone-naive datetime
    latest_end_time = max(end_times)
    if latest_end_time.tzinfo is not None:
        latest_end_time = latest_end_time.replace(tzinfo=None)

    return latest_end_time


def get_end_time(match: Match) -> datetime | None:
    """
    Get end time for a match:
    - If match is complete: true end time (completed_time)
    - Else if match is started: true start time + nominal length
    - Else: scheduled start time + nominal length
    """
    if match.status == "COMPLETED" and match.completed_time:
        end_time = match.completed_time
        # Ensure timezone-aware for consistency
        if end_time.tzinfo is None:
            end_time = end_time.replace(tzinfo=timezone.utc)
        return end_time

    start_time = (
        match.confirmed_start_time
        if match.status == "IN_PROGRESS"
        else match.nominal_start_time
    )

    if not start_time:
        return None

    # Ensure timezone-aware for calculations
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)

    return start_time + timedelta(minutes=match.nominal_length)


def topological_sort(matches: list[Match], get_deps_func) -> list[Match]:
    """
    Perform topological sort on matches based on dependencies.
    Returns list of matches in topological order.
    """
    # Build dependency graph
    graph = {match.uuid: match for match in matches}
    in_degree = {match.uuid: 0 for match in matches}

    # Calculate in-degrees
    for match in matches:
        deps = get_deps_func(match)
        for dep in deps:
            if dep.uuid in in_degree:
                in_degree[match.uuid] += 1

    # Kahn's algorithm for topological sort
    queue = [match for match in matches if in_degree[match.uuid] == 0]
    result = []

    while queue:
        match = queue.pop(0)
        result.append(match)

        # Find all matches that depend on this one
        for other_match in matches:
            if other_match.uuid != match.uuid:
                deps = get_deps_func(other_match)
                if any(dep.uuid == match.uuid for dep in deps):
                    in_degree[other_match.uuid] -= 1
                    if in_degree[other_match.uuid] == 0:
                        queue.append(other_match)

    # Handle cycles (matches not in result)
    remaining = [m for m in matches if m not in result]
    result.extend(remaining)

    return result


def get_deps(
    match: Match, tournament_url: str, include_time_finalized: bool = False
) -> list[Match]:
    """
    Get dependencies for a match based on the new rules:
    - If time_finalized: return none
    - STATIC (not dynamic): return none
    - DYNAMIC (dynamic and not BREAK/JOIN): team & ref dependencies + previous match
    - BREAK: previous match
    - JOIN: previous match for all joins with same name
    """
    if not include_time_finalized and match.time_finalized:
        return []

    # STATIC matches have no dependencies
    if match.schedule_type == "STATIC":
        return []

    deps = []

    # For JOIN matches: get previous match for all joins with same name
    if match.schedule_type == "JOIN":
        # Get all joins with the same name
        join_group = Match.query.filter_by(
            event=tournament_url, schedule_type="JOIN", name=match.name
        ).all()
        for jm in join_group:
            if jm.previous_match:
                prev_match = Match.query.filter_by(
                    uuid=jm.previous_match, event=tournament_url
                ).first()
                if prev_match and prev_match not in deps:
                    deps.append(prev_match)
    # For BREAK matches: get previous match
    elif match.schedule_type == "BREAK":
        if match.previous_match:
            prev_match = Match.query.filter_by(
                uuid=match.previous_match, event=tournament_url
            ).first()
            if prev_match:
                deps.append(prev_match)
    # For DYNAMIC matches (not BREAK/JOIN): team & ref dependencies + previous match
    else:  # DYNAMIC (SETS or STONES)
        # Add previous match
        if match.previous_match:
            prev_match = Match.query.filter_by(
                uuid=match.previous_match, event=tournament_url
            ).first()
            if prev_match:
                deps.append(prev_match)

        # Add team & ref dependencies
        ref_match_ids = referenced_match_ids(match, tournament_url)
        if ref_match_ids:
            ref_matches = Match.query.filter(
                Match.uuid.in_(ref_match_ids), Match.event == tournament_url
            ).all()
            for ref_match in ref_matches:
                if ref_match not in deps:
                    deps.append(ref_match)

    return deps


def recompute_all_match_times(tournament_url: str) -> None:
    """
    Recompute match times using the new algorithm:
    1. Compute dependencies for each match
    2. Build dependency graph and perform topological sort
    3. Process matches in reverse topological order
    4. Update start times and time_finalized based on match type
    """
    # Get all matches (expire_all ensures we get fresh data after previous commits)
    db.session.expire_all()
    all_matches = Match.query.filter_by(event=tournament_url).all()

    # Perform topological sort
    sorted_matches = topological_sort(
        all_matches, lambda x: get_deps(x, tournament_url)
    )

    for match in sorted_matches:
        db.session.flush()
        deps = get_deps(match, tournament_url, include_time_finalized=True)
        print(match.name, [m.name for m in deps] if deps else None)
        # If match has dependencies, set start time to max of dependency end times

        last_dep = max(deps, key=get_end_time) if deps else None
        if last_dep:
            match.nominal_start_time = get_end_time(last_dep).replace(tzinfo=None)

        if match.schedule_type != "STATIC":
            if not match.time_finalized:
                if last_dep and last_dep.started():
                    match.finalize()

        # Update ready_to_start based on dependency completion state
        # We need to get dependencies even if time_finalized is True, because we still need to check
        # if they're completed to determine ready_to_start
        deps_for_readiness = get_deps(match, tournament_url, True)

        if deps_for_readiness and all(
            dep.status == "COMPLETED" for dep in deps_for_readiness
        ):
            # Mark as ready to start and set timestamp if not already present
            match.ready_to_start = True
            if not match.ready_to_start_at:
                match.ready_to_start_at = datetime.now(timezone.utc).replace(
                    tzinfo=None
                )

    db.session.commit()


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
        cycle_paths: set[tuple[str, ...]] = (
            set()
        )  # Track unique cycles to avoid duplicates

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
                cycle_matches = [
                    match_dict[uuid].name for uuid in cycle if uuid in match_dict
                ]
                cycle_str = " -> ".join(cycle_matches)

                for uuid in cycle:
                    if uuid in match_dict:
                        if uuid not in cycles:
                            cycles[uuid] = []
                        cycles[uuid].append(
                            f"Circular dependency detected: {cycle_str}"
                        )

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
        this_length_minutes = (
            0 if match.schedule_type == "JOIN" else match.nominal_length
        )
        this_end = (
            match.completed_time
            if match.completed_time
            else this_start + timedelta(minutes=this_length_minutes)
        )
        # Collect all teams/refs for this match
        this_teams = set()
        if match.team1:
            this_teams.add(match.team1)
        if match.team2:
            this_teams.add(match.team2)
        if match.refs:
            this_teams.update(m.strip() for m in match.refs.split(",") if m.strip())

        # Also check initial fields for team references
        this_initials = set(_initial_tokens(match.team1_initial or ""))
        this_initials.update(_initial_tokens(match.team2_initial or ""))
        this_initials.update(_initial_tokens(match.refs_initial or ""))

        # Check against all other matches
        for other in matches:
            if other.uuid == match.uuid:
                continue

            if not other.nominal_start_time:
                continue

            other_start = other.nominal_start_time
            other_length_minutes = (
                0 if other.schedule_type == "JOIN" else other.nominal_length
            )
            other_end = (
                other.completed_time
                if other.completed_time
                else other_start + timedelta(minutes=other_length_minutes)
            )

            # Check for field overlap
            if match.field and other.field == match.field:
                # Check if time intervals overlap: [this_start, this_end) and [other_start, other_end)
                if this_start < other_end and other_start < this_end:
                    match_errors.append(
                        f"Overlaps on field '{match.field}' with match '{other.name}' ({other_start.strftime('%Y-%m-%d %H:%M')})"
                    )

            # Check for team double-booking
            other_teams = set()
            if other.team1:
                other_teams.add(other.team1)
            if other.team2:
                other_teams.add(other.team2)
            if other.refs:
                other_teams.update(
                    m.strip() for m in other.refs.split(",") if m.strip()
                )

            other_initials = set(_initial_tokens(other.team1_initial or ""))
            other_initials.update(_initial_tokens(other.team2_initial or ""))
            other_initials.update(_initial_tokens(other.refs_initial or ""))

            # Check if time intervals overlap
            if this_start < other_end and other_start < this_end:
                # Check for team conflicts
                team_conflict = this_teams & other_teams
                if team_conflict:
                    match_errors.append(
                        f"Team(s) {', '.join(team_conflict)} double-booked with match '{other.name}'"
                    )

                # Check for initial field conflicts (team names/references)
                initial_conflict = this_initials & other_initials
                if initial_conflict:
                    match_errors.append(
                        f"Team/ref '{', '.join(initial_conflict)}' double-booked with match '{other.name}'"
                    )

        if match_errors:
            conflicts[match.uuid] = match_errors

    return conflicts


def _predicted_end_time(m: Match) -> datetime | None:
    """Return predicted end time using nominal_start_time + nominal_length."""
    if not m or not m.nominal_start_time:
        return None
    start_time = m.nominal_start_time
    # JOIN matches have zero length
    if m.schedule_type == "JOIN":
        length_minutes = 0
    else:
        length_minutes = m.nominal_length or 60
    return start_time + timedelta(minutes=length_minutes)


def _extract_refs_from_text(text: str) -> list[tuple[str, str]]:
    """Extract (base, kind) pairs from a free text that may contain '...::winner' or '...::loser'."""
    refs: list[tuple[str, str]] = []
    if not text:
        return refs
    # Split by commas to catch multiple refs in refs_initial
    parts = [p.strip() for p in text.split(",") if p.strip()]
    for p in parts:
        # Check for new format: match_name::winner or match_name::loser
        if "::winner" in p or p.endswith("::winner"):
            base = p.split("::")[0].strip()
            refs.append((base, "winner"))
        elif "::loser" in p or p.endswith("::loser"):
            base = p.split("::")[0].strip()
            refs.append((base, "loser"))
        # Legacy support: also check for old format "match_name winner" or "match_name loser"
        else:
            low = " ".join(p.lower().split())
            if low.endswith(" winner"):
                base = p.rsplit(" ", 1)[0].strip()
                refs.append((base, "winner"))
            elif low.endswith(" loser"):
                base = p.rsplit(" ", 1)[0].strip()
                refs.append((base, "loser"))
    return refs


def _initial_tokens(text: str) -> list[str]:
    """Split an *_initial field by commas into simple tokens (trimmed, non-empty)."""
    if not text:
        return []
    return [p.strip() for p in text.split(",") if p.strip()]


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
    if match.schedule_type in ("BREAK", "JOIN"):
        # For JOIN matches, ensure length is 0
        if (
            match.schedule_type == "JOIN"
            and match.nominal_length
            and match.nominal_length != 0
        ):
            return False, "JOIN matches must have zero length."
        return True, None

    # For standard matches, require number of sets
    if match.nsets is None or int(match.nsets) <= 0:
        return (
            False,
            "Number of sets is required and must be > 0 for non-BREAK/JOIN matches.",
        )

    # Determine this match nominal start
    this_start = match.nominal_start_time
    if not this_start:
        return False, "Match start time could not be determined."

    # Collect references from team initials and refs_initial
    ref_tuples: list[tuple[str, str]] = []
    ref_tuples += _extract_refs_from_text(match.team1_initial or "")
    ref_tuples += _extract_refs_from_text(match.team2_initial or "")
    ref_tuples += _extract_refs_from_text(match.refs_initial or "")

    # Resolve and check each reference
    for base, kind in ref_tuples:
        ref_match = resolve_reference_to_match(base, tournament_url)
        if not ref_match:
            # If the user typed a result reference, base must resolve
            return False, f"Referenced match '{base}' was not found."
        # Self-reference is not allowed
        if match.uuid and ref_match.uuid == match.uuid:
            return (
                False,
                "A match cannot reference its own winner/loser for teams or refs.",
            )
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
        prev_match = Match.query.filter_by(
            uuid=match.previous_match, event=tournament_url
        ).first()
        if prev_match:
            deps.append(prev_match)

    # Add referenced matches from team1_initial, team2_initial, refs_initial
    ref_match_ids = referenced_match_ids(match, tournament_url)
    if ref_match_ids:
        ref_matches = Match.query.filter(
            Match.uuid.in_(ref_match_ids), Match.event == tournament_url
        ).all()
        deps.extend(ref_matches)

    return deps


def _compute_chain_end_time(
    start_match: Match, tournament_url: str, visited: set = None
) -> tuple[datetime | None, bool]:
    """
    Compute the end time of a chain of BREAK/JOIN matches starting from start_match.
    Returns (end_time, all_finalized) where:
    - end_time is the end time of the chain (None if chain is incomplete)
    - all_finalized is True if all matches in the chain have time_finalized=True
    Handles cycles by tracking visited matches.
    """
    if visited is None:
        visited = set()

    if start_match.uuid in visited:
        return None, False  # Cycle detected
    visited.add(start_match.uuid)

    # Get the start time of the first match in the chain
    start_time = start_match.confirmed_start_time or start_match.nominal_start_time
    if not start_time:
        return None, False

    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)

    # For BREAK/JOIN matches, we can compute the chain even if not explicitly finalized
    # as long as they have a start time. For other matches, they need to be finalized or started.
    if start_match.schedule_type not in ("BREAK", "JOIN"):
        # For non-BREAK/JOIN matches, they need to be finalized or have started
        if not start_match.time_finalized and start_match.status not in (
            "IN_PROGRESS",
            "COMPLETED",
        ):
            return None, False

    # Compute this match's end time
    if start_match.schedule_type == "JOIN":
        length_minutes = 0
    elif start_match.schedule_type == "BREAK":
        length_minutes = start_match.nominal_length or 60
    else:
        length_minutes = start_match.nominal_length or 60

    current_end = start_time + timedelta(minutes=length_minutes)

    # If this match has a next_match that's a BREAK/JOIN, continue the chain
    if start_match.next_match:
        next_match = Match.query.filter_by(
            uuid=start_match.next_match, event=tournament_url
        ).first()
        if next_match and next_match.schedule_type in ("BREAK", "JOIN"):
            # Recursively compute the chain
            chain_end, chain_finalized = _compute_chain_end_time(
                next_match, tournament_url, visited
            )
            if chain_end:
                return chain_end, chain_finalized and start_match.time_finalized
            else:
                # Chain is incomplete, but we can still return this match's end if it's finalized
                return current_end if start_match.time_finalized else None, False

    # End of chain
    return current_end, start_match.time_finalized


def mark_dependent_matches_ready_to_start(
    completed_match: Match, tournament_url: str
) -> None:
    """When a match finishes, mark all dependent matches as ready to start.
    A match is ready to start when the last dependency finishes.

    This function propagates through chains of BREAK/JOIN matches, marking matches
    at the end of chains as ready when all dependencies are complete.
    """
    # Find all matches that depend on this match (directly or through BREAK/JOIN chains)
    all_matches = Match.query.filter_by(event=tournament_url).all()

    for match in all_matches:
        if match.ready_to_start or match.started():
            continue

        deps = get_deps(match, tournament_url, True)
        if not deps:
            continue

        if completed_match.uuid not in [d.uuid for d in deps]:
            continue

        if all(dep.status == "COMPLETED" for dep in deps):
            match.ready_to_start = True
            if not match.ready_to_start_at:
                match.ready_to_start_at = datetime.now(tz=timezone.utc)

    # Commit changes
    db.session.commit()


def update_dynamic_schedule_after_completion(
    tournament_url: str, completed_match: Match
) -> None:
    """When a match ends, update dependent matches and handle BREAK/JOIN auto-completion.

    - Mark dependent matches as ready to start
    - Auto-complete BREAK matches if they're the next match
    - Auto-complete JOIN matches if all dependencies are finished
    - Pull forward subsequent dynamic matches on the same field
    """
    try:
        # # First, mark dependent matches as ready to start
        mark_dependent_matches_ready_to_start(completed_match, tournament_url)

        # Then handle field-based scheduling updates
        if not completed_match.field:
            db.session.commit()
            return

        # Ordered by nominal schedule to determine sequence
        field_matches = (
            Match.query.filter_by(event=tournament_url, field=completed_match.field)
            .order_by(Match.nominal_start_time.asc())
            .all()
        )

        # Locate the completed match within the field sequence
        index_map = {m.uuid: i for i, m in enumerate(field_matches)}
        if completed_match.uuid not in index_map:
            db.session.commit()
            return
        idx = index_map[completed_match.uuid]
        subsequent = field_matches[idx + 1 :]
        if not subsequent:
            db.session.commit()
            return

        # Stop at next static match (dynamic == False), not including it
        dynamic_chain = []
        for m in subsequent:
            if m.schedule_type == "STATIC":
                break
            dynamic_chain.append(m)

        if not dynamic_chain:
            db.session.commit()
            return

        def get_finalized_at(m: Match):
            if getattr(m, "completed_time", None):
                d = m.completed_time
                try:
                    if d and d.tzinfo is None:
                        d = d.replace(tzinfo=timezone.utc)
                except Exception:
                    pass
                return d

        end_ts = get_finalized_at(completed_match)
        if not end_ts:
            end_ts = datetime.now(timezone.utc)

        # 1) Immediately next match: update predicted nominal start to the end of
        # the completed match (no finalization here). Readiness is handled elsewhere.
        next_match = dynamic_chain[0]
        try:
            if next_match.status == "NOT_STARTED" and next_match.schedule_type not in (
                "BREAK",
                "JOIN",
            ):
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
        if next_match.schedule_type == "JOIN":
            next_match_length = 0
        else:
            next_match_length = next_match.nominal_length or default_minutes
        pointer = end_ts + timedelta(minutes=next_match_length)

        for m in dynamic_chain[1:]:
            if m.status in ("IN_PROGRESS", "COMPLETED"):
                continue  # Skip matches that have already started or completed

            # For JOIN matches, check ALL dependencies (across all fields), not just field-local ones
            # JOIN matches can only be pulled forward if their dependencies are ready
            deps_ready_at = None
            has_deps = False
            if m.schedule_type == "JOIN":
                deps = get_match_dependencies(m, tournament_url)
                has_deps = len(deps) > 0
                if deps:
                    # Check if all dependencies are completed
                    all_deps_completed = all(dep.status == "COMPLETED" for dep in deps)
                    if not all_deps_completed:
                        # Dependencies not ready - don't update time, but advance pointer by 0
                        continue
                    # All dependencies completed - get the latest end time
                    dep_final_times = []
                    for dep in deps:
                        ft = get_finalized_at(dep)
                        if ft:
                            dep_final_times.append(ft)
                    if dep_final_times:
                        deps_ready_at = max(dep_final_times)
            else:
                # For non-JOIN matches, compute dependency readiness from field-local references
                dep_ids = referenced_match_ids(m, tournament_url)
                has_deps = len(dep_ids) > 0
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
            if has_deps and deps_ready_at is None:
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
            if m.schedule_type == "JOIN":
                minutes = 0
            else:
                minutes = m.nominal_length or default_minutes
            pointer = effective_start + timedelta(minutes=minutes)

        db.session.commit()
    except Exception as e:
        # Log but don't raise to avoid breaking finalization
        print(
            f"update_dynamic_schedule_after_completion error on field {completed_match.field}: {e}"
        )
        db.session.rollback()
