"""
Scheduling logic for matches using the in-memory MatchGraph.

Implements PROCEDURE (per-match scheduling). Same flow on match create/edit
and on match start/end: build graph, topological sort, apply PROCEDURE, write back.
SAFE = finalize start time when last dependency is started.
FAST = finalize when all dependencies are completed.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from app.domain.enums import MatchStatus, ScheduleType
from app.models.base import db
from app.utils.MatchGraph import (
    MatchGraph,
    MatchGraphNode,
    build_match_graph,
)

_tournament_locks: Dict[str, threading.Lock] = {}
_locks_lock = threading.Lock()


def _get_tournament_lock(tournament_url: str) -> threading.Lock:
    with _locks_lock:
        if tournament_url not in _tournament_locks:
            _tournament_locks[tournament_url] = threading.Lock()
        return _tournament_locks[tournament_url]


def _now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _evaluate_skip_condition(
    tournament_url: str,
    node: MatchGraphNode,
    name_to_match: Dict,
) -> bool:
    """Evaluate the match's skip_condition DSL using in-memory match_resolver (no DB read)."""
    if not node.skip_condition or not node.skip_condition.strip():
        return False
    try:
        from app.utils.parser import Match as ParserMatch, get_parser, SymbolicMatch

        def match_resolver(name: str):
            m = name_to_match.get(name)
            if m is not None:
                return ParserMatch(m, tournament_url)
            return SymbolicMatch(name, tournament_url)

        parser = get_parser(tournament_url, match_resolver=match_resolver)
        result = parser.parse(node.skip_condition.strip())
        if isinstance(result, bool):
            return result
        return False
    except Exception:
        return False


def _all_schedule_deps_in(
    node: MatchGraphNode, statuses: Tuple[MatchStatus, ...]
) -> bool:
    deps = node.get_schedule_dependencies()
    if not deps:
        return True
    return all(dep.status in statuses for dep in deps)


def _procedure_with_match(
    graph: MatchGraph,
    node: MatchGraphNode,
    tournament_url: str,
    name_to_match: Dict,
) -> None:
    """
    PROCEDURE: WITH MATCH m

    Mutates node (nominal_start_time, status). No callbacks.
    """
    if node.status in (
        MatchStatus.COMPLETED,
        MatchStatus.IN_PROGRESS,
        MatchStatus.SKIPPED,
    ):
        return

    nominal_start_if_skipped: Optional[datetime] = None

    if node.schedule_type == ScheduleType.STATIC:
        if node.status == MatchStatus.NOT_STARTED:
            node.status = MatchStatus.TIME_FINALIZED

    elif node.schedule_type in (ScheduleType.BREAK, ScheduleType.JOIN):
        latest_end = node.get_direct_deps_latest_end_time()
        if latest_end is not None:
            node.nominal_start_time = latest_end

    elif node.schedule_type == ScheduleType.SAFE:
        if node.status == MatchStatus.NOT_STARTED:
            node.nominal_start_time = node.get_direct_deps_latest_end_time(
                for_safe_nominal=True
            )
            nominal_start_if_skipped = node.get_direct_deps_latest_end_time(
                for_safe_nominal=False
            )

    elif node.schedule_type == ScheduleType.FAST:
        if node.status == MatchStatus.NOT_STARTED:
            node.nominal_start_time = node.get_direct_deps_latest_end_time(
                for_safe_nominal=False
            )

    if _all_schedule_deps_in(node, (MatchStatus.COMPLETED, MatchStatus.SKIPPED)):
        skip_cond = _evaluate_skip_condition(tournament_url, node, name_to_match)
        if skip_cond:
            node.status = MatchStatus.SKIPPED
            node.nominal_start_time = (
                nominal_start_if_skipped
                if nominal_start_if_skipped is not None
                else node.nominal_start_time
            )
        else:
            if node.schedule_type in (
                ScheduleType.STATIC,
                ScheduleType.SAFE,
                ScheduleType.FAST,
            ):
                node.status = MatchStatus.READY_TO_START
            else:
                node.status = MatchStatus.COMPLETED

    elif node.schedule_type == ScheduleType.SAFE and _all_schedule_deps_in(
        node, (MatchStatus.IN_PROGRESS, MatchStatus.COMPLETED, MatchStatus.SKIPPED)
    ):
        node.status = MatchStatus.TIME_FINALIZED


def _write_graph_to_db(graph: MatchGraph, uuid_to_match: Dict[str, object]) -> None:
    """Persist graph state to in-memory Match objects (no DB read). Caller commits once."""
    for node in graph.get_all_nodes():
        uuids_to_update = (
            list(node.component_uuids) if node.component_uuids else [node.uuid]
        )
        for uid in uuids_to_update:
            m = uuid_to_match.get(uid)
            if m is not None:
                m.nominal_start_time = node.nominal_start_time
                m.status = node.status


def run_scheduling(tournament_url: str) -> None:
    """
    Single scheduling pass: load all matches, build graph, apply PROCEDURE, write back.
    Same behavior on match create/edit and on match start/end.
    """
    from app.models.match import Match

    lock = _get_tournament_lock(tournament_url)
    lock.acquire()
    try:
        all_matches = Match.query.filter_by(event=tournament_url).all()
        uuid_to_match = {m.uuid: m for m in all_matches}
        name_to_match = {}
        for m in all_matches:
            if m.name not in name_to_match:
                name_to_match[m.name] = m
        graph = build_match_graph(tournament_url, all_matches)
        order = graph.topological_sort()
        for name, field in order:
            node = graph.get_node(name, field)
            if node:
                _procedure_with_match(graph, node, tournament_url, name_to_match)
        _write_graph_to_db(graph, uuid_to_match)
        db.session.commit()
    finally:
        lock.release()


def recompute_all_match_times(tournament_url: str) -> None:
    """Full recompute of nominal times and statuses. Same as run_scheduling."""
    run_scheduling(tournament_url)


def get_match_dependencies(match, tournament_url: str) -> List:
    """
    Return list of Match rows that are schedule dependencies of the given match.
    Used by UI to check if dependencies are finished before allowing start.
    """
    from app.models.match import Match

    graph = build_match_graph(tournament_url)
    field = (
        ""
        if getattr(match, "schedule_type", None) == ScheduleType.JOIN
        else getattr(match, "field", None)
    )
    node = graph.get_node(match.name, field)
    if not node:
        return []
    schedule_deps = node.get_schedule_dependencies()
    if not schedule_deps:
        return []
    names = [n.name for n in schedule_deps]
    return Match.query.filter(
        Match.event == tournament_url,
        Match.name.in_(names),
    ).all()


def compute_dynamic_match_nominal_start_time(
    match, tournament_url: str
) -> Optional[datetime]:
    """
    Compute nominal_start_time for a SAFE/FAST/BREAK/JOIN match from the graph
    (for use when adding/editing a match before commit). Does not write to DB.
    """
    graph = build_match_graph(tournament_url)
    field = (
        ""
        if getattr(match, "schedule_type", None) == ScheduleType.JOIN
        else getattr(match, "field", None)
    )
    node = graph.get_node(match.name, field)
    if not node:
        return None
    if node.schedule_type in (ScheduleType.BREAK, ScheduleType.JOIN):
        return node.get_direct_deps_latest_end_time()
    if node.schedule_type == ScheduleType.SAFE:
        return node.get_direct_deps_latest_end_time(for_safe_nominal=True)
    if node.schedule_type == ScheduleType.FAST:
        return node.get_direct_deps_latest_end_time(for_safe_nominal=False)
    return None


def validate_match_input(match, tournament_url: str) -> Tuple[bool, Optional[str]]:
    """
    Validate match fields (name, teams, times, etc.). Returns (True, None) or (False, error_message).
    """
    if not match.name or not match.name.strip():
        return False, "Match name is required."
    if "::" in match.name:
        return False, 'Match names cannot contain "::".'
    from app.models.match import Match

    existing = Match.query.filter_by(
        event=tournament_url,
        name=match.name.strip(),
    )
    if match.uuid:
        existing = existing.filter(Match.uuid != match.uuid)
    if existing.first() and getattr(match, "schedule_type", None) not in (
        "BREAK",
        "JOIN",
    ):
        return False, "A match with this name already exists."
    return True, None


def detect_match_conflicts(tournament_url: str) -> List[dict]:
    """
    Detect scheduling conflicts (e.g. overlapping matches on same field).
    Returns a list of conflict descriptors for the UI.
    """
    from datetime import timedelta
    from app.models.match import Match

    matches = Match.query.filter_by(event=tournament_url).all()
    conflicts = []
    for m in matches:
        if not m.field or not m.nominal_start_time or not m.nominal_length:
            continue
        end = m.nominal_start_time + timedelta(minutes=m.nominal_length or 0)
        for other in matches:
            if other.uuid == m.uuid or not other.field or other.field != m.field:
                continue
            if not other.nominal_start_time or not other.nominal_length:
                continue
            other_end = other.nominal_start_time + timedelta(
                minutes=other.nominal_length
            )
            if m.nominal_start_time < other_end and end > other.nominal_start_time:
                conflicts.append(
                    {"match1": m.name, "match2": other.name, "field": m.field}
                )
    return conflicts
