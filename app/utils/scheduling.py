"""
Scheduling logic for matches using the in-memory MatchGraph.

Implements PROCEDURE (per-match scheduling). Same flow on match create/edit
and on match start/end: build graph, topological sort, apply PROCEDURE, write back.
SAFE = finalize start time when last dependency is started.
FAST = finalize when all dependencies are completed.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from app.domain.enums import MatchStatus, ScheduleType
from app.models.base import db
from app.utils.MatchGraph import (
    MatchGraph,
    MatchGraphNode,
    build_match_graph,
)
from app.utils.name_validation import match_name_char_error

_tournament_locks: Dict[str, threading.Lock] = {}
_locks_lock = threading.Lock()


def _get_tournament_lock(tournament_url: str) -> threading.Lock:
    with _locks_lock:
        if tournament_url not in _tournament_locks:
            _tournament_locks[tournament_url] = threading.Lock()
        return _tournament_locks[tournament_url]


def _now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _csv_tokens(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    return [part.strip() for part in str(raw).split(",") if part.strip()]


def _match_participant_team_ids(match: object) -> set[str]:
    participants = set()
    for team_id in (getattr(match, "team1", None), getattr(match, "team2", None)):
        if team_id and str(team_id).strip():
            participants.add(str(team_id).strip())
    participants.update(_csv_tokens(getattr(match, "refs", None)))
    return participants


def _matches_share_any_team(match_a: object, match_b: object) -> bool:
    return bool(_match_participant_team_ids(match_a) & _match_participant_team_ids(match_b))


def _intervals_overlap(
    start_a: Optional[datetime],
    length_a: Optional[int],
    start_b: Optional[datetime],
    length_b: Optional[int],
) -> bool:
    if (
        start_a is None
        or start_b is None
        or length_a is None
        or length_b is None
    ):
        return False
    end_a = start_a + timedelta(minutes=length_a)
    end_b = start_b + timedelta(minutes=length_b)
    return start_a < end_b and end_a > start_b


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


def _slot_resolved(
    team_id: Optional[str],
    initial: Optional[str],
    tournament_url: str,
    name_to_match: Dict,
    tag_by_name: Optional[Dict[str, object]] = None,
) -> bool:
    """True if this team/ref slot is resolved to a specific team (or is empty)."""
    if team_id and str(team_id).strip():
        return True
    if not initial or not str(initial).strip():
        return True
    initial = str(initial).strip()
    if initial.lower().startswith("tag::"):
        from app.models.tournament import Tag

        tag_name = initial[5:].strip()
        if tag_by_name is not None:
            tag = tag_by_name.get(tag_name)
        else:
            tag = Tag.query.filter_by(event=tournament_url, name=tag_name).first()
        return bool(tag and getattr(tag, "team", None))
    if "::winner" in initial or "::loser" in initial:
        base = initial.split("::")[0].strip()
        dep = name_to_match.get(base)
        return bool(dep and getattr(dep, "match_winner", None) is not None)
    return False


def _all_participating_teams_resolved(
    match: object,
    tournament_url: str,
    name_to_match: Dict,
    tag_by_name: Optional[Dict[str, object]] = None,
) -> bool:
    """
    True if all participating teams (team1, team2, refs) are fully resolved:
    each slot is either a concrete team ID, or a tag:: ref with the tag assigned to a team,
    or a MatchName::winner/loser ref whose match is completed.
    """
    from app.domain.enums import ScheduleType

    schedule_type = getattr(match, "schedule_type", None)
    if schedule_type in (ScheduleType.BREAK, ScheduleType.JOIN):
        return True

    if not _slot_resolved(
        getattr(match, "team1", None),
        getattr(match, "team1_initial", None),
        tournament_url,
        name_to_match,
        tag_by_name,
    ):
        return False
    if not _slot_resolved(
        getattr(match, "team2", None),
        getattr(match, "team2_initial", None),
        tournament_url,
        name_to_match,
        tag_by_name,
    ):
        return False

    refs_raw = (getattr(match, "refs", None) or "") or ""
    refs_initial_raw = (getattr(match, "refs_initial", None) or "") or ""
    refs_parts = [p.strip() for p in refs_raw.split(",")]
    refs_initial_parts = [p.strip() for p in refs_initial_raw.split(",")]
    n_refs = max(len(refs_parts), len(refs_initial_parts))
    for i in range(n_refs):
        team_id = refs_parts[i] if i < len(refs_parts) else None
        initial = refs_initial_parts[i] if i < len(refs_initial_parts) else None
        if not team_id and not initial:
            continue
        if not _slot_resolved(
            team_id, initial, tournament_url, name_to_match, tag_by_name
        ):
            return False

    return True


def _procedure_with_match(
    graph: MatchGraph,
    node: MatchGraphNode,
    tournament_url: str,
    name_to_match: Dict,
    tag_by_name: Optional[Dict[str, object]] = None,
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
                # Only mark READY_TO_START when all teams/refs are fully resolved
                if _all_participating_teams_resolved(
                    name_to_match[node.name],
                    tournament_url,
                    name_to_match,
                    tag_by_name,
                ):
                    node.status = MatchStatus.READY_TO_START
                # else: leave at TIME_FINALIZED (or NOT_STARTED for STATIC) until resolved
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
    from app.models.tournament import Tag

    lock = _get_tournament_lock(tournament_url)
    lock.acquire()
    try:
        all_matches = Match.query.filter_by(event=tournament_url).all()
        tags = Tag.query.filter_by(event=tournament_url).all()
        tag_by_name = {t.name: t for t in tags}
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
                _procedure_with_match(
                    graph, node, tournament_url, name_to_match, tag_by_name
                )
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
    mn_err = match_name_char_error(match.name)
    if mn_err:
        return False, mn_err
    from app.models.match import Match

    schedule_type = getattr(match, "schedule_type", None)
    existing = Match.query.filter_by(
        event=tournament_url,
        name=match.name.strip(),
    )
    # For BREAK/JOIN, only check uniqueness on the same field and same type
    if schedule_type in (ScheduleType.BREAK, ScheduleType.JOIN):
        field = (getattr(match, "field", None) or "").strip()
        existing = existing.filter(
            Match.field == field, Match.schedule_type == schedule_type
        )
    if match.uuid:
        existing = existing.filter(Match.uuid != match.uuid)
    if existing.first():
        return False, "A match with this name already exists."

    conflicts = Match.query.filter_by(event=tournament_url)
    if match.uuid:
        conflicts = conflicts.filter(Match.uuid != match.uuid)
    for other in conflicts.all():
        if not _matches_share_any_team(match, other):
            continue
        if (
            schedule_type in (ScheduleType.SAFE, ScheduleType.FAST)
            and other.schedule_type in (ScheduleType.SAFE, ScheduleType.FAST)
            and match.nominal_start_time is not None
            and match.nominal_start_time == other.nominal_start_time
        ):
            return (
                False,
                f"FAST/SAFE match shares a team with '{other.name}' and cannot have the same nominal start time.",
            )
        if (
            schedule_type == ScheduleType.STATIC
            and other.schedule_type == ScheduleType.STATIC
            and _intervals_overlap(
                match.nominal_start_time,
                match.nominal_length,
                other.nominal_start_time,
                other.nominal_length,
            )
        ):
            return (
                False,
                f"Static match overlaps with '{other.name}' while sharing a team.",
            )
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
