"""
MatchGraph: In-memory DAG representation of matches for topological sorting.

This module provides a graph-based approach to match scheduling that avoids
repeated database queries by storing match data and dependencies in memory.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional, Set, Dict, List

from app.models.match import Match
from app.domain.enums import ScheduleType, MatchStatus


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
        min_warning: int = 5,
    ):
        self.name = name
        self.uuid = uuid
        self.nominal_start_time = nominal_start_time
        self.nominal_length = nominal_length
        self.confirmed_start_time = confirmed_start_time
        self.confirmed_end_time = confirmed_end_time
        self.schedule_type = schedule_type
        self.skip_condition = skip_condition
        self.status = status
        self.min_warning = min_warning
        # For JOIN matches: set of UUIDs of component matches
        self.component_uuids = component_uuids or set()
        # Dependencies: set of Dependency wrappers (startOfMatchDep or endOfMatchDep)
        self.dependencies: Set["Dependency"] = set()
        # Reverse dependencies: matches that depend on this node
        self.dependents: Set["MatchGraphNode"] = set()

    def __repr__(self) -> str:
        return f"MatchGraphNode(name={self.name!r}, uuid={self.uuid}, deps={len(self.dependencies)})"

    def get_schedule_dependencies(self) -> Set["MatchGraphNode"]:
        """
        Get schedule dependencies by traversing the dependency tree.

        Returns only STATIC or DYNAMIC matches, skipping over BREAK, JOIN, and SKIPPED matches.
        Traverses through BREAK, JOIN, and SKIPPED matches as if they have no dependencies,
        effectively finding the "real" scheduling dependencies.

        Returns:
            Set of nodes that are STATIC or DYNAMIC and are schedule dependencies
        """
        result: Set["MatchGraphNode"] = set()
        visited: Set["MatchGraphNode"] = set()

        def traverse(node: "MatchGraphNode") -> None:
            """Recursively traverse dependencies, collecting STATIC/DYNAMIC matches."""
            if node in visited:
                return
            visited.add(node)

            # If this is a STATIC or DYNAMIC match and not SKIPPED, add it and stop traversing
            if (
                node.schedule_type in (ScheduleType.STATIC, ScheduleType.DYNAMIC)
                and node.status != MatchStatus.SKIPPED
            ):
                result.add(node)
                return

            # For BREAK, JOIN, and SKIPPED matches, continue traversing their dependencies
            # (treat them as transparent in the dependency chain)
            for dep in node.dependencies:
                traverse(dep.node)

        # Start traversal from this node's dependencies
        for dep in self.dependencies:
            traverse(dep.node)

        return result

    def get_deps_latest_end_time(self) -> Optional[datetime]:
        """
        Get the latest end time from all normal dependencies (not schedule dependencies).

        For skip-condition dependencies, uses start time instead of end time.
        For other dependencies, uses end time with appropriate fallbacks.

        Returns:
            Latest end/start time from dependencies, or None if no dependencies
        """
        if not self.dependencies:
            return None

        latest_time: Optional[datetime] = None
        for dep in self.dependencies:
            time_to_use = dep.get_time()
            if time_to_use:
                if latest_time is None or time_to_use > latest_time:
                    latest_time = time_to_use

        return latest_time


def _node_start_time(node: MatchGraphNode) -> Optional[datetime]:
    """Effective start time of a node (confirmed or nominal)."""
    return node.confirmed_start_time or node.nominal_start_time


def _node_end_time(node: MatchGraphNode) -> Optional[datetime]:
    """Effective end time of a node (confirmed_end_time or start + length fallbacks)."""
    if node.confirmed_end_time:
        return node.confirmed_end_time
    if node.confirmed_start_time and node.nominal_length:
        return node.confirmed_start_time + timedelta(minutes=node.nominal_length)
    if node.nominal_start_time and node.nominal_length:
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

    Nodes represent matches (or groups of JOIN matches with the same name).
    Edges represent dependencies: if match A depends on match B, there is an edge B -> A.

    This allows efficient topological sorting without repeated database queries.
    """

    def __init__(self):
        # Map from match name to node (for JOIN matches, all components share one node)
        self.nodes_by_name: Dict[str, MatchGraphNode] = {}
        # Map from match UUID to node name (for reverse lookup)
        self.uuid_to_name: Dict[str, str] = {}
        # Map from match name to set of component UUIDs (for JOIN matches)
        self.name_to_uuids: Dict[str, Set[str]] = defaultdict(set)

    def add_node(self, node: MatchGraphNode) -> None:
        """Add a node to the graph."""
        self.nodes_by_name[node.name] = node
        self.uuid_to_name[node.uuid] = node.name
        if node.component_uuids:
            self.name_to_uuids[node.name].update(node.component_uuids)
        else:
            self.name_to_uuids[node.name].add(node.uuid)

    def get_node(self, name: str) -> Optional[MatchGraphNode]:
        """Get a node by match name."""
        return self.nodes_by_name.get(name)

    def add_dependency(
        self,
        dependent_name: str,
        dependency_name: str,
        *,
        is_skip_condition: bool = False,
    ) -> None:
        """
        Add a dependency edge: dependent_name depends on dependency_name.

        Args:
            dependent_name: Name of the match that depends on another
            dependency_name: Name of the match that is depended upon
            is_skip_condition: If True, use startOfMatchDep (effective time = start);
                if False, use endOfMatchDep (effective time = end).
        """
        dependent = self.nodes_by_name.get(dependent_name)
        dependency_node = self.nodes_by_name.get(dependency_name)

        if dependent and dependency_node:
            dep: Dependency = (
                startOfMatchDep(dependency_node)
                if is_skip_condition
                else endOfMatchDep(dependency_node)
            )
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
        in_degree: Dict[MatchGraphNode, int] = {
            node: len(node.dependencies) for node in self.nodes_by_name.values()
        }

        # Queue of nodes with no incoming edges
        queue: List[MatchGraphNode] = [node for node, degree in in_degree.items() if degree == 0]

        result: List[str] = []

        while queue:
            # Remove a node with no incoming edges
            node = queue.pop(0)
            result.append(node.name)

            # For each dependent, reduce in-degree
            for dependent_node in node.dependents:
                in_degree[dependent_node] -= 1
                if in_degree[dependent_node] == 0:
                    queue.append(dependent_node)

        # Check for cycles
        if len(result) != len(self.nodes_by_name):
            remaining = set(self.nodes_by_name.keys()) - set(result)
            raise ValueError(f"Cycle detected in match dependencies. Remaining nodes: {remaining}")

        return result

    def get_all_nodes(self) -> List[MatchGraphNode]:
        """Get all nodes in the graph."""
        return list(self.nodes_by_name.values())


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

    # Map from match name to list of Match objects (for handling JOIN matches)
    matches_by_name: Dict[str, List[Match]] = defaultdict(list)
    # Map from UUID to Match object
    matches_by_uuid: Dict[str, Match] = {}

    for match in all_matches:
        matches_by_name[match.name].append(match)
        matches_by_uuid[match.uuid] = match

    # Create nodes: JOIN matches with the same name share a single node
    for match_name, match_list in matches_by_name.items():
        # Check if any of these matches are JOIN type
        join_matches = [m for m in match_list if m.schedule_type == ScheduleType.JOIN]

        if join_matches:
            # All JOIN matches with the same name form a single node
            # Use the first one as the representative, but collect all UUIDs
            representative = join_matches[0]
            component_uuids = {m.uuid for m in join_matches}

            min_warning = getattr(representative, "min_warning", None) or 5
            node = MatchGraphNode(
                name=representative.name,
                uuid=representative.uuid,  # Use first UUID as primary
                nominal_start_time=representative.nominal_start_time,
                nominal_length=representative.nominal_length,
                confirmed_start_time=representative.confirmed_start_time,
                confirmed_end_time=representative.finalized_at,
                schedule_type=representative.schedule_type,
                skip_condition=representative.skip_condition,
                status=representative.status,
                component_uuids=component_uuids,
                min_warning=min_warning,
            )
            graph.add_node(node)
        else:
            # Non-JOIN matches: each match is its own node
            # If there are multiple matches with the same name (shouldn't happen for non-JOIN),
            # we'll use the first one
            match = match_list[0]
            min_warning = getattr(match, "min_warning", None) or 5
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
                min_warning=min_warning,
            )
            graph.add_node(node)

    # Build dependency edges
    for match_name, match_list in matches_by_name.items():
        # For JOIN matches, process all components to collect dependencies
        join_matches = [m for m in match_list if m.schedule_type == ScheduleType.JOIN]

        if join_matches:
            # For JOIN matches: collect dependencies from all components
            all_deps: Set[str] = set()
            skip_condition_deps: Set[str] = set()

            for join_match in join_matches:
                # previous_match dependency
                if join_match.previous_match:
                    prev_match = matches_by_uuid.get(join_match.previous_match)
                    if prev_match:
                        # Find the node name for this match (could be a JOIN group)
                        prev_node_name = prev_match.name
                        # If the previous match is also a JOIN, it's already in the graph
                        all_deps.add(prev_node_name)

                # Skip condition dependencies
                skip_deps = join_match.get_skip_condition_dependencies()
                all_deps.update(skip_deps.get("direct", set()))
                all_deps.update(skip_deps.get("skip_condition", set()))
                # Track which are skip-condition dependencies
                skip_condition_deps.update(skip_deps.get("skip_condition", set()))

            # Add dependencies with correct type (startOfMatchDep vs endOfMatchDep)
            for dep_name in all_deps:
                if dep_name in graph.nodes_by_name:
                    graph.add_dependency(
                        match_name,
                        dep_name,
                        is_skip_condition=(dep_name in skip_condition_deps),
                    )
        else:
            # Non-JOIN matches: process normally
            match = match_list[0]

            # Dependencies from team1_initial, team2_initial, refs_initial
            # Check for MatchName::winner or MatchName::loser references that are not resolved
            for initial_field in [match.team1_initial, match.team2_initial, match.refs_initial]:
                refs = _extract_match_references(initial_field or "")
                for ref_match_name, ref_type in refs:
                    # Find the match by name
                    ref_match_list = matches_by_name.get(ref_match_name)
                    if ref_match_list:
                        # Check if any of the matches with this name are resolved
                        # For JOIN matches, they don't have match_winner, so they're always unresolved
                        # For non-JOIN matches, check if resolved
                        ref_match = ref_match_list[0]
                        # JOIN matches can't be resolved (they don't have winners)
                        if ref_match.schedule_type == ScheduleType.JOIN:
                            # JOIN matches are always dependencies if referenced
                            graph.add_dependency(match_name, ref_match_name)
                        elif not _is_match_resolved(ref_match):
                            # This is a dependency
                            graph.add_dependency(match_name, ref_match_name)

            # previous_match dependency
            if match.previous_match:
                prev_match = matches_by_uuid.get(match.previous_match)
                if prev_match:
                    prev_node_name = prev_match.name
                    graph.add_dependency(match_name, prev_node_name)

            # Skip condition dependencies (direct -> endOfMatchDep, skip_condition -> startOfMatchDep)
            skip_deps = match.get_skip_condition_dependencies()
            direct_skip_deps = skip_deps.get("direct", set())
            skip_condition_deps = skip_deps.get("skip_condition", set())
            for dep_name in direct_skip_deps:
                if dep_name in graph.nodes_by_name:
                    graph.add_dependency(match_name, dep_name, is_skip_condition=False)
            for dep_name in skip_condition_deps:
                if dep_name in graph.nodes_by_name:
                    graph.add_dependency(match_name, dep_name, is_skip_condition=True)

    return graph
