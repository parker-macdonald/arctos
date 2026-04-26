"""
MatchGraph: In-memory DAG representation of matches for topological sorting.

This module provides a graph-based approach to match scheduling that avoids
repeated database queries by storing match data and dependencies in memory.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional, Set, Dict, List, Tuple

from app.models.match import Match
from app.domain.enums import ScheduleType, MatchStatus


def _node_key(name: str, field: Optional[str]) -> Tuple[str, str]:
    """Return the canonical graph key for a match node.

    Matches on different fields with the same name are treated as distinct
    nodes.

    Args:
        name: Match name.
        field: Field (court) name, or ``None``.

    Returns:
        A ``(name, field_or_empty)`` tuple used as the dict key.
    """
    return (name, field or "")


class MatchGraphNode:
    """Represents a single node in the match dependency graph."""

    def __init__(
        self,
        name: str,
        uuid: str,
        nominal_start_time: Optional[datetime],
        nominal_length: Optional[int],
        confirmed_start_time: Optional[datetime],
        confirmed_end_time: Optional[datetime],
        schedule_type: ScheduleType,
        skip_condition: Optional[str],
        status: MatchStatus,
        component_uuids: Optional[Set[str]] = None,
        field: Optional[str] = None,
    ):
        self.name = name
        self.field = field or ""
        self.uuid = uuid
        self.nominal_start_time = nominal_start_time
        self.nominal_length = nominal_length
        self.confirmed_start_time = confirmed_start_time
        self.confirmed_end_time = confirmed_end_time
        self.schedule_type = schedule_type
        self.skip_condition = skip_condition
        self.status = status
        # For JOIN matches: set of UUIDs of component matches
        self.component_uuids = component_uuids or set()
        # Dependencies: set of Dependency wrappers (startOfMatchDep or endOfMatchDep)
        self.dependencies: Set["Dependency"] = set()
        # Reverse dependencies: matches that depend on this node
        self.dependents: Set["MatchGraphNode"] = set()

    def __repr__(self) -> str:
        return f"MatchGraphNode(name={self.name!r}, uuid={self.uuid}, deps={len(self.dependencies)})"

    def get_direct_dependencies(self) -> Set["MatchGraphNode"]:
        """
        Dependencies that contribute to nominal start time (end-of-match deps only).
        Used for computing latest end time for SAFE/FAST/BREAK/JOIN.
        """
        from app.utils.MatchGraph import endOfMatchDep

        return set(dep.node for dep in self.dependencies if isinstance(dep, endOfMatchDep))

    def get_schedule_dependencies(self) -> Set["MatchGraphNode"]:
        """
        Get schedule dependencies by traversing the dependency tree.

        Returns only STATIC, SAFE, or FAST matches; skips over BREAK, JOIN, and SKIPPED.
        Used to decide when this match becomes READY_TO_START / TIME_FINALIZED.
        """
        result: Set["MatchGraphNode"] = set()
        visited: Set["MatchGraphNode"] = set()

        def traverse(node: "MatchGraphNode") -> None:
            if node in visited:
                return
            visited.add(node)
            if (
                node.schedule_type in (ScheduleType.STATIC, ScheduleType.SAFE, ScheduleType.FAST)
                # and node.status != MatchStatus.SKIPPED # idt we should do this bc we know skipping only happens at match start
            ):
                result.add(node)
                return
            for dep in node.dependencies:
                traverse(dep.node)

        for dep in self.dependencies:
            traverse(dep.node)
        return result

    def get_direct_deps_latest_end_time(self, for_safe_nominal: bool = False) -> Optional[datetime]:
        """
        Latest end time from direct (end-of-match) dependencies only.

        - for_safe_nominal=False (FAST/BREAK/JOIN): latest END_TIME(x) for each direct dep.
        - for_safe_nominal=True (SAFE nominal_start): for each direct dep x,
          if x is SKIPPED use END_TIME(x) + x.nominal_length else END_TIME(x); take latest.
        """

        if not self.dependencies:
            return None
        latest_time: Optional[datetime] = None
        for dep in self.dependencies:
            time_to_use = dep.get_time()
            if for_safe_nominal and dep.node.status == MatchStatus.SKIPPED:
                time_to_use = time_to_use + timedelta(minutes=dep.node.nominal_length)
            if time_to_use and (latest_time is None or time_to_use > latest_time):
                latest_time = time_to_use
        return latest_time


def _node_start_time(node: MatchGraphNode) -> Optional[datetime]:
    """Effective start time of a node (confirmed or nominal)."""
    return node.confirmed_start_time or node.nominal_start_time


def _node_end_time(node: MatchGraphNode) -> Optional[datetime]:
    """Effective end time of a node (confirmed_end_time or start + length fallbacks)."""
    if node.status == MatchStatus.SKIPPED:
        return node.nominal_start_time
    if node.confirmed_end_time:
        return node.confirmed_end_time
    if node.confirmed_start_time:
        return node.confirmed_start_time + timedelta(minutes=node.nominal_length)
    if node.nominal_start_time:
        return node.nominal_start_time + timedelta(minutes=node.nominal_length)
    return None


class Dependency(ABC):
    """
    Abstract wrapper around a pointer to a MatchGraphNode.

    Hashes and compares equal to other Dependencies that wrap the same node,
    so it can be used in sets and as dict keys. Subclasses define get_time()
    to return the effective time used for scheduling (start vs end of match).

    For dependencies that come from (is-skipped MATCH) (the non-direct group
    from Match.get_skip_condition_dependencies()), the effective time is the
    match's start time. For other dependencies, it is the match's end time.
    """

    def __init__(self, node: MatchGraphNode) -> None:
        self._node = node

    @property
    def node(self) -> MatchGraphNode:
        return self._node

    def __hash__(self) -> int:
        return hash(self._node)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Dependency):
            return NotImplemented
        return self._node is other._node

    @abstractmethod
    def get_time(self) -> Optional[datetime]:
        """Return the effective time for this dependency (start or end of the wrapped match)."""
        ...


class startOfMatchDep(Dependency):
    """
    Dependency whose effective time is the match's start time.

    Used for dependencies that are (is-skipped MATCH) (skip_condition group
    from get_skip_condition_dependencies()).
    """

    def get_time(self) -> Optional[datetime]:
        return _node_start_time(self._node)


class endOfMatchDep(Dependency):
    """
    Dependency whose effective time is the match's end time.

    Used for direct dependencies (winner/loser, previous_match, etc.).
    """

    def get_time(self) -> Optional[datetime]:
        return _node_end_time(self._node)


class MatchGraph:
    """
    Directed acyclic graph (DAG) representation of matches for scheduling.

    Nodes represent matches (or groups of JOIN matches with the same name on the same field).
    Keys are (name, field) so matches with the same name on different fields are distinct nodes.
    Edges represent dependencies: if match A depends on match B, there is an edge B -> A.
    """

    def __init__(self):
        # Map from (name, field) to node. Same name on different fields = different nodes.
        self.nodes_by_key: Dict[Tuple[str, str], MatchGraphNode] = {}
        # Map from match UUID to (name, field) for reverse lookup
        self.uuid_to_key: Dict[str, Tuple[str, str]] = {}
        # Map from (name, field) to set of component UUIDs (for JOIN matches)
        self.key_to_uuids: Dict[Tuple[str, str], Set[str]] = defaultdict(set)

    def add_node(self, node: MatchGraphNode) -> None:
        """Add a node to the graph. Key is (node.name, node.field)."""
        key = _node_key(node.name, node.field)
        self.nodes_by_key[key] = node
        self.uuid_to_key[node.uuid] = key
        if node.component_uuids:
            self.key_to_uuids[key].update(node.component_uuids)
        else:
            self.key_to_uuids[key].add(node.uuid)

    def get_node(self, name: str, field: Optional[str] = None) -> Optional[MatchGraphNode]:
        """Get a node by match name and field. field defaults to ''."""
        key = _node_key(name, field)
        return self.nodes_by_key.get(key)

    def add_dependency(
        self,
        dependent_key: Tuple[str, str],
        dependency_key: Tuple[str, str],
        *,
        is_skip_condition: bool = False,
    ) -> None:
        """
        Add a dependency edge: dependent depends on dependency.

        Args:
            dependent_key: (name, field) of the match that depends on another
            dependency_key: (name, field) of the match that is depended upon
            is_skip_condition: If True, use startOfMatchDep; if False, use endOfMatchDep.
        """
        dependent = self.nodes_by_key.get(dependent_key)
        dependency_node = self.nodes_by_key.get(dependency_key)

        if dependent and dependency_node:
            dep: Dependency = startOfMatchDep(dependency_node) if is_skip_condition else endOfMatchDep(dependency_node)
            dependent.dependencies.add(dep)
            dependency_node.dependents.add(dependent)

    def get_dependencies(self, match_name: str) -> Set["Dependency"]:
        """Get the set of Dependency wrappers that the given match depends on."""
        node = self.nodes_by_name.get(match_name)
        return node.dependencies.copy() if node else set()

    def get_dependents(self, match_name: str) -> Set[MatchGraphNode]:
        """Get the set of nodes that depend on the given match."""
        node = self.nodes_by_name.get(match_name)
        return node.dependents.copy() if node else set()

    def topological_sort(self) -> List[str]:
        """
        Perform topological sort of match names.

        Returns:
            List of match names in topological order (dependencies before dependents).

        Raises:
            ValueError: If the graph contains cycles.
        """
        # Kahn's algorithm for topological sort
        # Calculate in-degree for each node
        in_degree: Dict[MatchGraphNode, int] = {node: len(node.dependencies) for node in self.nodes_by_key.values()}

        # Queue of nodes with no incoming edges
        queue: List[MatchGraphNode] = [node for node, degree in in_degree.items() if degree == 0]

        result: List[Tuple[str, str]] = []

        while queue:
            node = queue.pop(0)
            result.append(_node_key(node.name, node.field))

            # For each dependent, reduce in-degree
            for dependent_node in node.dependents:
                in_degree[dependent_node] -= 1
                if in_degree[dependent_node] == 0:
                    queue.append(dependent_node)

        # Check for cycles
        if len(result) != len(self.nodes_by_key):
            remaining = set(self.nodes_by_key.keys()) - set(result)
            raise ValueError(f"Cycle detected in match dependencies. Remaining nodes: {remaining}")

        return result

    def get_all_nodes(self) -> List[MatchGraphNode]:
        """Get all nodes in the graph."""
        return list(self.nodes_by_key.values())


def _extract_match_references(text: str) -> List[tuple[str, str]]:
    """
    Extract match references from text (team1_initial, team2_initial, refs_initial).

    Returns:
        List of (match_name, reference_type) tuples where reference_type is "winner" or "loser".
    """
    refs: List[tuple[str, str]] = []
    if not text:
        return refs

    # Split by commas to catch multiple refs in refs_initial
    parts = [p.strip() for p in text.split(",") if p.strip()]
    for p in parts:
        # Check for new format: match_name::winner or match_name::loser
        if p.endswith("::winner"):
            base = p.split("::")[0].strip()
            refs.append((base, "winner"))
        elif p.endswith("::loser"):
            base = p.split("::")[0].strip()
            refs.append((base, "loser"))
    return refs


def _is_match_resolved(match: Match) -> bool:
    """Check if a match has been resolved (winner/loser determined)."""
    return match.match_winner is not None


def _csv_tokens(raw: Optional[str]) -> List[str]:
    """Split a comma-separated string into a trimmed list, dropping empty parts.

    Args:
        raw: A comma-separated string, or ``None``.

    Returns:
        List of non-empty stripped tokens.
    """
    if not raw:
        return []
    return [part.strip() for part in str(raw).split(",") if part.strip()]


def _match_participant_team_ids(match: Match) -> Set[str]:
    """Return concrete team IDs currently assigned to team or ref slots."""
    participants = set()
    for team_id in (getattr(match, "team1", None), getattr(match, "team2", None)):
        if team_id and str(team_id).strip():
            participants.add(str(team_id).strip())
    participants.update(_csv_tokens(getattr(match, "refs", None)))
    return participants


def build_match_graph(
    tournament_url: str,
    all_matches: Optional[List[Match]] = None,
) -> MatchGraph:
    """
    Build a MatchGraph from all matches in a tournament.

    If all_matches is provided, uses that list (no DB query). Otherwise queries
    all matches for the tournament once.

    Args:
        tournament_url: The tournament URL to build the graph for
        all_matches: Optional pre-loaded list of Match rows; if None, queries DB

    Returns:
        MatchGraph containing all matches and their dependencies
    """
    if all_matches is None:
        all_matches = Match.query.filter_by(event=tournament_url).all()

    graph = MatchGraph()

    # Map from (name, field) to list of Match objects (for non-JOIN and for dependency resolution)
    matches_by_key: Dict[Tuple[str, str], List[Match]] = defaultdict(list)
    # JOIN matches grouped by name only: one logical node per name across all fields
    joins_by_name: Dict[str, List[Match]] = defaultdict(list)
    matches_by_uuid: Dict[str, Match] = {}
    matches_by_field: Dict[str, List[Match]] = defaultdict(list)

    for match in all_matches:
        key = _node_key(match.name, getattr(match, "field", None))
        matches_by_key[key].append(match)
        matches_by_uuid[match.uuid] = match
        if getattr(match, "field", None):
            matches_by_field[match.field].append(match)
        if match.schedule_type == ScheduleType.JOIN:
            joins_by_name[match.name].append(match)

    join_names: Set[str] = set(joins_by_name.keys())

    def dep_key_for_match(m: Match) -> Tuple[str, str]:
        """Resolve (name, field) key for a match: JOIN uses (name, ''), non-JOIN uses (name, field)."""
        if m.schedule_type == ScheduleType.JOIN:
            return (m.name, "")
        return _node_key(m.name, getattr(m, "field", None))

    # Create nodes: one node per JOIN name (key = (name, "")), one node per (name, field) for non-JOIN
    for name, join_list in joins_by_name.items():
        representative = join_list[0]
        component_uuids = {m.uuid for m in join_list}
        node = MatchGraphNode(
            name=representative.name,
            uuid=representative.uuid,
            nominal_start_time=representative.nominal_start_time,
            nominal_length=representative.nominal_length,
            confirmed_start_time=representative.confirmed_start_time,
            confirmed_end_time=representative.finalized_at,
            schedule_type=representative.schedule_type,
            skip_condition=representative.skip_condition,
            status=representative.status,
            component_uuids=component_uuids,
            field="",
        )
        graph.add_node(node)

    for key, match_list in matches_by_key.items():
        if all(m.schedule_type == ScheduleType.JOIN for m in match_list):
            continue  # already created above
        match = match_list[0]
        node = MatchGraphNode(
            name=match.name,
            uuid=match.uuid,
            nominal_start_time=match.nominal_start_time,
            nominal_length=match.nominal_length,
            confirmed_start_time=match.confirmed_start_time,
            confirmed_end_time=match.finalized_at,
            schedule_type=match.schedule_type,
            skip_condition=match.skip_condition,
            status=match.status,
            field=match.field or "",
        )
        graph.add_node(node)

    # Build dependency edges
    for name in join_names:
        dependent_key = (name, "")
        join_matches = joins_by_name[name]
        all_dep_keys: Set[Tuple[str, str]] = set()
        skip_condition_dep_keys: Set[Tuple[str, str]] = set()

        for join_match in join_matches:
            if join_match.previous_match:
                prev_match = matches_by_uuid.get(join_match.previous_match)
                if prev_match:
                    all_dep_keys.add(dep_key_for_match(prev_match))

            skip_deps = join_match.get_skip_condition_dependencies()
            for dep_name in skip_deps.get("direct", set()) | skip_deps.get("skip_condition", set()):
                if dep_name in join_names:
                    dep_key = (dep_name, "")
                else:
                    dep_key = (dep_name, join_match.field or "")
                if dep_key not in graph.nodes_by_key:
                    for k in graph.nodes_by_key:
                        if k[0] == dep_name:
                            dep_key = k
                            break
                if dep_key in graph.nodes_by_key:
                    all_dep_keys.add(dep_key)
                    if dep_name in skip_deps.get("skip_condition", set()):
                        skip_condition_dep_keys.add(dep_key)

        for dep_key in all_dep_keys:
            if dep_key in graph.nodes_by_key:
                graph.add_dependency(
                    dependent_key,
                    dep_key,
                    is_skip_condition=(dep_key in skip_condition_dep_keys),
                )

    for key, match_list in matches_by_key.items():
        if all(m.schedule_type == ScheduleType.JOIN for m in match_list):
            continue
        match_name, match_field = key
        dependent_key = key
        match = match_list[0]

        for initial_field in [
            match.team1_initial,
            match.team2_initial,
            match.refs_initial,
        ]:
            refs = _extract_match_references(initial_field or "")
            for ref_match_name, ref_type in refs:
                if ref_match_name in join_names:
                    ref_key = (ref_match_name, "")
                else:
                    ref_key = (ref_match_name, match_field)
                if ref_key not in graph.nodes_by_key:
                    for k in graph.nodes_by_key:
                        if k[0] == ref_match_name:
                            ref_key = k
                            break
                if ref_key in graph.nodes_by_key:
                    ref_list = matches_by_key.get(ref_key)
                    if ref_list:
                        ref_match = ref_list[0]
                        if ref_match.schedule_type == ScheduleType.JOIN:
                            graph.add_dependency(dependent_key, ref_key)
                        elif not _is_match_resolved(ref_match):
                            graph.add_dependency(dependent_key, ref_key)
                    else:
                        # ref_key is a JOIN node (name, ""); no entry in matches_by_key
                        graph.add_dependency(dependent_key, ref_key)

        if match.previous_match:
            prev_match = matches_by_uuid.get(match.previous_match)
            if prev_match:
                prev_key = dep_key_for_match(prev_match)
                graph.add_dependency(dependent_key, prev_key)

        if match.schedule_type in (ScheduleType.SAFE, ScheduleType.FAST):
            match_start = getattr(match, "nominal_start_time", None)
            participants = _match_participant_team_ids(match)
            latest_shared_matches_by_field: Dict[str, Match] = {}
            if match_start and participants:
                for field_name, field_matches in matches_by_field.items():
                    latest_shared_match = None
                    for candidate in field_matches:
                        candidate_start = getattr(candidate, "nominal_start_time", None)
                        if candidate.uuid == match.uuid or candidate_start is None or candidate_start >= match_start:
                            continue
                        if not (participants & _match_participant_team_ids(candidate)):
                            continue
                        if latest_shared_match is None or (
                            candidate_start,
                            candidate.name,
                            candidate.uuid,
                        ) > (
                            latest_shared_match.nominal_start_time,
                            latest_shared_match.name,
                            latest_shared_match.uuid,
                        ):
                            latest_shared_match = candidate
                    if latest_shared_match is not None:
                        latest_shared_matches_by_field[field_name] = latest_shared_match
            for latest_shared_match in latest_shared_matches_by_field.values():
                latest_shared_key = dep_key_for_match(latest_shared_match)
                graph.add_dependency(dependent_key, latest_shared_key)

        skip_deps = match.get_skip_condition_dependencies()
        direct_skip_deps = skip_deps.get("direct", set())
        skip_condition_deps = skip_deps.get("skip_condition", set())
        for dep_name in direct_skip_deps:
            dep_key = (dep_name, match_field) if dep_name not in join_names else (dep_name, "")
            if dep_key not in graph.nodes_by_key:
                for k in graph.nodes_by_key:
                    if k[0] == dep_name:
                        dep_key = k
                        break
            if dep_key in graph.nodes_by_key:
                graph.add_dependency(dependent_key, dep_key, is_skip_condition=False)
        for dep_name in skip_condition_deps:
            dep_key = (dep_name, match_field) if dep_name not in join_names else (dep_name, "")
            if dep_key not in graph.nodes_by_key:
                for k in graph.nodes_by_key:
                    if k[0] == dep_name:
                        dep_key = k
                        break
            if dep_key in graph.nodes_by_key:
                graph.add_dependency(dependent_key, dep_key, is_skip_condition=True)

    return graph
