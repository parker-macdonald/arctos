"""
Scheduling logic for matches using the in-memory MatchGraph.

Implements PROCEDURE (per-match scheduling), on match start/end, and on match
create/edit. Uses topological sort over the dependency graph and optional
scheduled callbacks for TIME_FINALIZED transitions.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional, Tuple

from app.domain.enums import MatchStatus, ScheduleType
from app.models.base import db
from app.utils.MatchGraph import (
    MatchGraph,
    MatchGraphNode,
    build_match_graph,
)

# Per-tournament locks for serializing scheduling updates.
_tournament_locks: Dict[str, threading.Lock] = {}
_locks_lock = threading.Lock()

# Scheduled callbacks: tournament_url -> match_uuid -> (run_at_utc, callback).
_scheduled_callbacks: Dict[str, Dict[str, Tuple[datetime, Callable[[], None]]]] = {}
_callbacks_lock = threading.Lock()


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
        # Resolver: resolve match name from in-memory name_to_match (first match per name).
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
    now: datetime,
    name_to_match: Dict,
    schedule_callback: Callable[[str, str, datetime, Callable[[], None]], None],
    cancel_callbacks_for_match: Callable[[str, str], None],
) -> None:
    """
    PROCEDURE: WITH MATCH m

    Mutates node (nominal_start_time, status) and may register a callback.
    Uses node.min_warning for timing.
    """
    if node.status in (MatchStatus.COMPLETED, MatchStatus.IN_PROGRESS, MatchStatus.SKIPPED):
        return

    min_warn = getattr(node, "min_warning", 0)
    min_warning = timedelta(minutes=min_warn)

    # Set nominal_start_time by schedule type
    if node.schedule_type == ScheduleType.STATIC:
        pass
    elif node.schedule_type in (ScheduleType.BREAK, ScheduleType.JOIN):
        latest_end = node.get_deps_latest_end_time()
        print(f"latest_end: {node.name}: {latest_end}")
        print([(d.node.name, d.get_time()) for d in node.dependencies])
        if latest_end is not None:
            node.nominal_start_time = latest_end
    elif node.schedule_type == ScheduleType.DYNAMIC:
        if node.status == MatchStatus.NOT_STARTED:
            latest_end = node.get_deps_latest_end_time()

            candidates = [now + min_warning]
            if latest_end is not None:
                candidates.append(latest_end)
            node.nominal_start_time = max(candidates)

    # Schedule dependency state transitions
    schedule_deps = node.get_schedule_dependencies()

    if _all_schedule_deps_in(node, (MatchStatus.COMPLETED, MatchStatus.SKIPPED)):
        # All deps done: evaluate skip and set READY_TO_START / COMPLETED / SKIPPED
        skip_cond = _evaluate_skip_condition(tournament_url, node, name_to_match)
        if skip_cond:
            node.status = MatchStatus.SKIPPED
        else:
            if node.schedule_type in (ScheduleType.STATIC, ScheduleType.DYNAMIC):
                node.status = MatchStatus.READY_TO_START
            else:
                node.status = MatchStatus.COMPLETED

    elif _all_schedule_deps_in(
        node, (MatchStatus.IN_PROGRESS, MatchStatus.COMPLETED, MatchStatus.SKIPPED)
    ):
        node.status = MatchStatus.TIME_FINALIZED

    elif _all_schedule_deps_in(
        node,
        (
            MatchStatus.TIME_FINALIZED,
            MatchStatus.READY_TO_START,
            MatchStatus.IN_PROGRESS,
            MatchStatus.COMPLETED,
            MatchStatus.SKIPPED,
        ),
    ):
        if node.nominal_start_time is not None and node.status == MatchStatus.NOT_STARTED:
            callback_at = node.nominal_start_time - min_warning
            if callback_at >= now:
                uuids = list(node.component_uuids) if node.component_uuids else [node.uuid]
                minutes = min_warn

                def callback() -> None:
                    from app.models.match import Match
                    for uid in uuids:
                        m = Match.query.filter_by(uuid=uid, event=tournament_url).first()
                        if m and m.status == MatchStatus.NOT_STARTED:
                            m.nominal_start_time = _now_utc() + timedelta(minutes=minutes)
                            m.status = MatchStatus.TIME_FINALIZED
                    db.session.commit()
                    # run_scheduling_on_match_start_end(tournament_url)

                cancel_callbacks_for_match(tournament_url, node.uuid)
                schedule_callback(tournament_url, node.uuid, callback_at, callback)
            else:
                # Already past callback time: finalize now
                node.nominal_start_time = now + min_warning
                node.status = MatchStatus.TIME_FINALIZED


def _schedule_callback(
    tournament_url: str,
    match_uuid: str,
    run_at: datetime,
    callback: Callable[[], None],
) -> None:
    with _callbacks_lock:
        if tournament_url not in _scheduled_callbacks:
            _scheduled_callbacks[tournament_url] = {}
        _scheduled_callbacks[tournament_url][match_uuid] = (run_at, callback)


def _cancel_callbacks_for_tournament(tournament_url: str) -> None:
    with _callbacks_lock:
        _scheduled_callbacks.pop(tournament_url, None)


def _cancel_callbacks_for_match(tournament_url: str, match_uuid: str) -> None:
    with _callbacks_lock:
        if tournament_url in _scheduled_callbacks:
            _scheduled_callbacks[tournament_url].pop(match_uuid, None)


def get_tournaments_with_pending_callbacks() -> List[str]:
    """Return list of tournament URLs that have at least one scheduled callback."""
    with _callbacks_lock:
        return list(_scheduled_callbacks.keys())


def run_pending_callbacks(tournament_url: str) -> None:
    """Run any scheduled callbacks for this tournament that are due. Call from cron/worker."""
    now = _now_utc()
    with _callbacks_lock:
        to_run = []
        if tournament_url in _scheduled_callbacks:
            for match_uuid, (run_at, cb) in list(_scheduled_callbacks[tournament_url].items()):
                if run_at <= now:
                    to_run.append((match_uuid, cb))
            for match_uuid, _ in to_run:
                _scheduled_callbacks[tournament_url].pop(match_uuid, None)
    for _match_uuid, cb in to_run:
        try:
            cb()
        except Exception:
            pass


def _write_graph_to_db(graph: MatchGraph, uuid_to_match: Dict[str, object]) -> None:
    """Persist graph state to in-memory Match objects (no DB read). Caller commits once."""
    for node in graph.get_all_nodes():
        uuids_to_update = list(node.component_uuids) if node.component_uuids else [node.uuid]
        for uid in uuids_to_update:
            m = uuid_to_match.get(uid)
            if m is not None:
                m.nominal_start_time = node.nominal_start_time
                m.status = node.status


def _set_initial_finalized_from_beginning(
    graph: MatchGraph,
    now: datetime,
) -> None:
    """
    On create/edit: set TIME_FINALIZED / READY_TO_START on matches that are
    finalized from the beginning (static matches; dynamic matches following
    static in a window up to node.min_warning).
    """
    for node in graph.get_all_nodes():
        if node.status != MatchStatus.NOT_STARTED:
            continue
        min_warn = getattr(node, "min_warning", None) or DEFAULT_MIN_WARNING_MINUTES
        min_warning = timedelta(minutes=min_warn)
        if node.schedule_type == ScheduleType.STATIC:
            node.status = MatchStatus.READY_TO_START
        elif node.schedule_type == ScheduleType.DYNAMIC:
            schedule_deps = node.get_schedule_dependencies()
            if not schedule_deps:
                continue
            all_deps_ready = all(
                d.status in (MatchStatus.READY_TO_START, MatchStatus.COMPLETED, MatchStatus.SKIPPED)
                for d in schedule_deps
            )
            if all_deps_ready and node.nominal_start_time is not None:
                if node.nominal_start_time <= now + min_warning:
                    node.status = MatchStatus.TIME_FINALIZED


def run_scheduling_on_match_start_end(tournament_url: str) -> None:
    """
    On match start or end: single DB read (all matches), all work in memory, single commit.
    """
    from app.models.match import Match
    lock = _get_tournament_lock(tournament_url)
    lock.acquire()
    try:
        _cancel_callbacks_for_tournament(tournament_url)
        # Single read: load all matches for the tournament
        all_matches = Match.query.filter_by(event=tournament_url).all()
        uuid_to_match = {m.uuid: m for m in all_matches}
        name_to_match = {}
        for m in all_matches:
            if m.name not in name_to_match:
                name_to_match[m.name] = m
        graph = build_match_graph(tournament_url, all_matches)
        order = graph.topological_sort()
        now = _now_utc()
        for name, field in order:
            node = graph.get_node(name, field)
            if node:
                _procedure_with_match(
                    graph,
                    node,
                    tournament_url,
                    now,
                    name_to_match,
                    _schedule_callback,
                    _cancel_callbacks_for_match,
                )
        _write_graph_to_db(graph, uuid_to_match)
        db.session.commit()
    finally:
        lock.release()


def run_scheduling_on_match_create_edit(tournament_url: str) -> None:
    """
    On match create/edit: single read, in-memory work, single commit.
    First set TIME_FINALIZED/READY on matches finalized from the beginning.
    """
    from app.models.match import Match
    lock = _get_tournament_lock(tournament_url)
    lock.acquire()
    try:
        _cancel_callbacks_for_tournament(tournament_url)
        all_matches = Match.query.filter_by(event=tournament_url).all()
        uuid_to_match = {m.uuid: m for m in all_matches}
        name_to_match = {}
        for m in all_matches:
            if m.name not in name_to_match:
                name_to_match[m.name] = m
        graph = build_match_graph(tournament_url, all_matches)
        now = _now_utc()
        _set_initial_finalized_from_beginning(graph, now)
        order = graph.topological_sort()
        for name, field in order:
            node = graph.get_node(name, field)
            if node:
                _procedure_with_match(
                    graph,
                    node,
                    tournament_url,
                    now,
                    name_to_match,
                    _schedule_callback,
                    _cancel_callbacks_for_match,
                )
        _write_graph_to_db(graph, uuid_to_match)
        db.session.commit()
    finally:
        lock.release()


def recompute_all_match_times(
    tournament_url: str,
    *,
    after_create_edit: bool = False,
) -> None:
    """
    Full recompute of nominal times and statuses.

    - After match start or match finalize: call with default (after_create_edit=False).
    - After match create or edit: call with after_create_edit=True so that
      TIME_FINALIZED/READY_TO_START are set for static and dynamic-in-window matches first.
    """
    if after_create_edit:
        run_scheduling_on_match_create_edit(tournament_url)
    else:
        run_scheduling_on_match_start_end(tournament_url)


def get_match_dependencies(match, tournament_url: str) -> List:
    """
    Return list of Match rows that are schedule dependencies of the given match.
    Used by UI to check if dependencies are finished before allowing start.
    """
    from app.models.match import Match
    graph = build_match_graph(tournament_url)
    # JOIN matches share one node keyed by (name, ""); non-JOIN by (name, field)
    field = "" if getattr(match, "schedule_type", None) == ScheduleType.JOIN else getattr(match, "field", None)
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


def compute_dynamic_match_nominal_start_time(match, tournament_url: str) -> Optional[datetime]:
    """
    Compute nominal_start_time for a dynamic/BREAK/JOIN match from the graph
    (for use when adding/editing a match before commit). Does not write to DB.
    Uses match.min_warning when applicable.
    """
    graph = build_match_graph(tournament_url)
    # JOIN matches share one node keyed by (name, ""); non-JOIN by (name, field)
    field = "" if getattr(match, "schedule_type", None) == ScheduleType.JOIN else getattr(match, "field", None)
    node = graph.get_node(match.name, field)
    if not node:
        return None
    now = _now_utc()
    min_warn = getattr(match, "min_warning", None) or DEFAULT_MIN_WARNING_MINUTES
    if node.schedule_type in (ScheduleType.BREAK, ScheduleType.JOIN):
        return node.get_deps_latest_end_time()
    if node.schedule_type == ScheduleType.DYNAMIC:
        latest_end = node.get_deps_latest_end_time()
        candidates = [now + timedelta(minutes=min_warn)]
        if latest_end is not None:
            candidates.append(latest_end)
        return max(candidates)
    return None


def validate_match_input(match, tournament_url: str) -> Tuple[bool, Optional[str]]:
    """
    Validate match fields (name, teams, times, etc.). Returns (True, None) or (False, error_message).
    """
    if not match.name or not match.name.strip():
        return False, "Match name is required."
    if "::" in match.name:
        return False, 'Match names cannot contain "::".'
    # Uniqueness: non-BREAK/JOIN must have unique name per tournament
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
            other_end = other.nominal_start_time + timedelta(minutes=other.nominal_length)
            if m.nominal_start_time < other_end and end > other.nominal_start_time:
                conflicts.append({
                    "match1": m.name,
                    "match2": other.name,
                    "field": m.field,
                })
    return conflicts
