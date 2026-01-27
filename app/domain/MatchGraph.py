"""
MatchGraph: In-memory DAG representation of matches for topological sorting.

This module provides a graph-based approach to match scheduling that avoids
repeated database queries by storing match data and dependencies in memory.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
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
        # For JOIN matches: set of UUIDs of component matches
        self.component_uuids = component_uuids or set()
        # Dependencies: set of match names this node depends on
        self.dependencies: Set[str] = set()
        # Reverse dependencies: matches that depend on this node
        self.dependents: Set[str] = set()

    def __repr__(self) -> str:
        return f"MatchGraphNode(name={self.name!r}, uuid={self.uuid}, deps={len(self.dependencies)})"

    def get_schedule_dependencies(self, graph: "MatchGraph") -> Set[str]:
        """
        Get schedule dependencies by traversing the dependency tree.

        Returns only STATIC or DYNAMIC matches, skipping over BREAK and JOIN matches.
        Traverses through BREAK and JOIN matches as if they have no dependencies,
        effectively finding the "real" scheduling dependencies.

        Args:
            graph: The MatchGraph containing all nodes

        Returns:
            Set of match names that are STATIC or DYNAMIC and are schedule dependencies
        """
        result: Set[str] = set()
        visited: Set[str] = set()

        def traverse(node_name: str) -> None:
            """Recursively traverse dependencies, collecting STATIC/DYNAMIC matches."""
            if node_name in visited:
                return
            visited.add(node_name)

            node = graph.get_node(node_name)
            if not node:
                return

            # If this is a STATIC or DYNAMIC match, add it and stop traversing
            if node.schedule_type in (ScheduleType.STATIC, ScheduleType.DYNAMIC):
                result.add(node_name)
                return

            # For BREAK and JOIN matches, continue traversing their dependencies
            # (treat them as transparent in the dependency chain)
            for dep_name in node.dependencies:
                traverse(dep_name)

        # Start traversal from this node's dependencies
        for dep_name in self.dependencies:
            traverse(dep_name)

        return result


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

    def add_dependency(self, dependent_name: str, dependency_name: str) -> None:
        """
        Add a dependency edge: dependent_name depends on dependency_name.

        Args:
            dependent_name: Name of the match that depends on another
            dependency_name: Name of the match that is depended upon
        """
        dependent = self.nodes_by_name.get(dependent_name)
        dependency = self.nodes_by_name.get(dependency_name)

        if dependent and dependency:
            dependent.dependencies.add(dependency_name)
            dependency.dependents.add(dependent_name)

    def get_dependencies(self, match_name: str) -> Set[str]:
        """Get the set of match names that the given match depends on."""
        node = self.nodes_by_name.get(match_name)
        return node.dependencies.copy() if node else set()

    def get_dependents(self, match_name: str) -> Set[str]:
        """Get the set of match names that depend on the given match."""
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
        in_degree: Dict[str, int] = {
            name: len(node.dependencies) for name, node in self.nodes_by_name.items()
        }

        # Queue of nodes with no incoming edges
        queue: List[str] = [name for name, degree in in_degree.items() if degree == 0]

        result: List[str] = []

        while queue:
            # Remove a node with no incoming edges
            node_name = queue.pop(0)
            result.append(node_name)

            # For each dependent, reduce in-degree
            node = self.nodes_by_name[node_name]
            for dependent_name in node.dependents:
                in_degree[dependent_name] -= 1
                if in_degree[dependent_name] == 0:
                    queue.append(dependent_name)

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

def build_match_graph(tournament_url: str) -> MatchGraph:
    """
    Build a MatchGraph from all matches in a tournament.

    This function queries all matches once and builds the complete dependency graph
    in memory, avoiding repeated database calls during topological sorting.

    Args:
        tournament_url: The tournament URL to build the graph for

    Returns:
        MatchGraph containing all matches and their dependencies
    """
    from app.models.base import db

    # Query all matches for the tournament
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
            )
            graph.add_node(node)
        else:
            # Non-JOIN matches: each match is its own node
            # If there are multiple matches with the same name (shouldn't happen for non-JOIN),
            # we'll use the first one
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
            )
            graph.add_node(node)

    # Build dependency edges
    for match_name, match_list in matches_by_name.items():
        # For JOIN matches, process all components to collect dependencies
        join_matches = [m for m in match_list if m.schedule_type == ScheduleType.JOIN]

        if join_matches:
            # For JOIN matches: collect dependencies from all components
            all_deps: Set[str] = set()

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

            # Add all collected dependencies to the JOIN node
            for dep_name in all_deps:
                if dep_name in graph.nodes_by_name:
                    graph.add_dependency(match_name, dep_name)
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

            # Skip condition dependencies
            skip_deps = match.get_skip_condition_dependencies()
            for dep_name in skip_deps.get("direct", set()):
                if dep_name in graph.nodes_by_name:
                    graph.add_dependency(match_name, dep_name)
            for dep_name in skip_deps.get("skip_condition", set()):
                if dep_name in graph.nodes_by_name:
                    graph.add_dependency(match_name, dep_name)

    return graph
