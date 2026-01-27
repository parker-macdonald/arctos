"""
Dependency analyzer for DSL skip-condition expressions.

This module provides functionality to analyze DSL expressions and determine
which matches they depend on, and what type of dependency (direct or skip-condition).
"""

from lark import Lark, Tree, Token
from typing import Set, Tuple, Dict
import os


class MatchDependencyAnalyzer:
    """
    Analyzes DSL expressions to find match dependencies.

    Dependencies are categorized as:
    - direct: The match must be completed (winner/loser determined) for the expression to evaluate
    - skip_condition: The match's skip_condition must be reducible to a boolean for this expression
    """

    # Functions that require match completion (direct dependencies)
    # Note: points-won and points-lost take TEAM as first arg, MATCH as optional second arg
    DIRECT_DEPENDENCY_FUNCTIONS = {"winner", "loser", "points-won", "points-lost"}

    # Functions where match is the first argument
    DIRECT_DEPENDENCY_FUNCTIONS_MATCH_FIRST = {"winner", "loser"}

    # Functions where match is the second argument (first is TEAM)
    DIRECT_DEPENDENCY_FUNCTIONS_MATCH_SECOND = {"points-won", "points-lost"}

    # Functions that require skip-condition evaluation
    SKIP_CONDITION_DEPENDENCY_FUNCTIONS = {"skip-condition"}

    def __init__(self, event: str):
        """
        Initialize the analyzer.

        Args:
            event: Tournament URL for resolving match names
        """
        self.event = event
        grammar_path = os.path.join(os.path.dirname(__file__), "grammar.lark")
        with open(grammar_path, "r") as g:
            self.parser = Lark(g, parser="lalr")

    def analyze(
        self, expression: str, visited_matches: Set[str] = None
    ) -> Dict[str, Set[str]]:
        """
        Analyze a DSL expression to find match dependencies.

        Args:
            expression: DSL expression string (skip-condition)
            visited_matches: Set of match names already being analyzed (for cycle detection)

        Returns:
            Dictionary with keys:
            - "direct": Set of match names that must be completed
            - "skip_condition": Set of match names whose skip_conditions must be evaluable
        """
        if not expression or not expression.strip():
            return {"direct": set(), "skip_condition": set()}

        if visited_matches is None:
            visited_matches = set()

        try:
            tree = self.parser.parse(expression.strip())
            dependencies = {"direct": set(), "skip_condition": set()}
            self._visit(tree, dependencies, visited_matches)
            return dependencies
        except Exception as e:
            # If parsing fails, return empty dependencies
            # (the expression will be validated elsewhere)
            # Note: We don't log errors here to avoid noise - the expression will be validated
            # by the actual parser when it's used
            return {"direct": set(), "skip_condition": set()}

    def _visit(
        self, tree, dependencies: Dict[str, Set[str]], visited_matches: Set[str]
    ):
        """
        Recursively visit AST nodes to find dependencies.

        Args:
            tree: Lark Tree node or Token
            dependencies: Dictionary to accumulate dependencies
            visited_matches: Set of matches already being analyzed (for cycle detection)
        """
        if isinstance(tree, Token):
            return

        if not isinstance(tree, Tree):
            return

        # Handle different node types
        if tree.data == "list":
            self._visit_list(tree, dependencies, visited_matches)
        elif tree.data == "match_atom":
            # This is a match reference - it will be used in a function call context
            # The context will determine the dependency type
            pass  # Handled by parent list node
        elif tree.data == "team_atom":
            # Team atoms might contain match references like [Match1::winner]
            # Extract match names from team literals
            if tree.children:
                token = tree.children[0]
                if isinstance(token, Token):
                    team_literal = token.value[1:-1]  # Remove brackets
                    # Check if it's a MatchName::winner or MatchName::loser reference
                    if "::" in team_literal:
                        parts = team_literal.split("::", 1)
                        if len(parts) == 2:
                            match_name, qualifier = parts
                            if qualifier in {"winner", "loser"}:
                                # This is a direct dependency (match must be completed to know winner/loser)
                                dependencies["direct"].add(match_name)
                                # Recursively analyze this match's skip condition if not already visited
                                if match_name not in visited_matches:
                                    self._analyze_match_skip_condition(
                                        match_name, dependencies, visited_matches
                                    )
        elif tree.data in {"expression", "atom", "start"}:
            # Visit children (these are wrapper nodes)
            for child in tree.children:
                self._visit(child, dependencies, visited_matches)
        else:
            # Visit all children for any other node type
            for child in tree.children:
                self._visit(child, dependencies, visited_matches)

    def _visit_list(
        self, tree: Tree, dependencies: Dict[str, Set[str]], visited_matches: Set[str]
    ):
        """
        Visit a list/s-expression node.

        Args:
            tree: List Tree node
            dependencies: Dictionary to accumulate dependencies
            visited_matches: Set of matches already being analyzed
        """
        if not tree.children:
            return

        # Get the function name (first child)
        head = tree.children[0]
        function_name = None

        if isinstance(head, Tree):
            if head.data == "identifier_atom":
                if head.children and isinstance(head.children[0], Token):
                    function_name = head.children[0].value
            elif head.data == "expression":
                # Recursively get function name
                function_name = self._extract_function_name(head)
            elif head.data == "atom" and head.children:
                # Handle atom wrapper
                atom_child = head.children[0]
                if (
                    isinstance(atom_child, Tree)
                    and atom_child.data == "identifier_atom"
                ):
                    if atom_child.children and isinstance(
                        atom_child.children[0], Token
                    ):
                        function_name = atom_child.children[0].value
        elif isinstance(head, Token):
            function_name = head.value

        # Check if this is a function that takes match arguments
        # Note: function_name might be None if we couldn't extract it
        if function_name and function_name in self.DIRECT_DEPENDENCY_FUNCTIONS:
            # Find match arguments
            if function_name in self.DIRECT_DEPENDENCY_FUNCTIONS_MATCH_FIRST:
                # winner, loser: MATCH is first argument
                if tree.children[1:]:
                    arg = tree.children[1]  # First argument is the match
                    match_name = self._extract_match_name(arg)
                    if match_name:
                        dependencies["direct"].add(match_name)
                        # Recursively analyze this match's skip condition if not already visited
                        if match_name not in visited_matches:
                            self._analyze_match_skip_condition(
                                match_name, dependencies, visited_matches
                            )
                    # Also recursively visit to find nested dependencies
                    self._visit(arg, dependencies, visited_matches)
            elif function_name in self.DIRECT_DEPENDENCY_FUNCTIONS_MATCH_SECOND:
                # points-won, points-lost: TEAM is first arg, MATCH is optional second arg
                if len(tree.children) > 2:
                    arg = tree.children[2]  # Second argument is the match (if present)
                    match_name = self._extract_match_name(arg)
                    if match_name:
                        dependencies["direct"].add(match_name)
                        # Recursively analyze this match's skip condition if not already visited
                        if match_name not in visited_matches:
                            self._analyze_match_skip_condition(
                                match_name, dependencies, visited_matches
                            )
                    # Also recursively visit to find nested dependencies
                    self._visit(arg, dependencies, visited_matches)
                # Also visit first argument (TEAM) to find match references in team literals like [Match1::winner]
                if tree.children[1:]:
                    self._visit(tree.children[1], dependencies, visited_matches)

        elif (
            function_name and function_name in self.SKIP_CONDITION_DEPENDENCY_FUNCTIONS
        ):
            # skip-condition takes a MATCH argument, but it might be an expression that evaluates to a match
            # We need to find all match atoms in the argument expression
            for arg in tree.children[1:]:
                # Find all match atoms in the argument (could be nested in if expressions, etc.)
                match_atoms = set()
                self._find_all_match_atoms(arg, match_atoms)

                # All match atoms found in the skip-condition argument are skip-condition dependencies
                # BUT: if a match is used in a winner/loser/etc call, it's a direct dependency, not skip-condition
                # So we'll add them as skip-condition for now, but the recursive visit will add direct ones too
                for match_name in match_atoms:
                    dependencies["skip_condition"].add(match_name)
                    # Recursively analyze this match's skip condition (if not already visited)
                    if match_name not in visited_matches:
                        visited_matches.add(match_name)
                        self._analyze_match_skip_condition(
                            match_name, dependencies, visited_matches
                        )
                        visited_matches.remove(match_name)

                # Also recursively visit to find other dependencies (like winner calls)
                # This will find direct dependencies and add them
                self._visit(arg, dependencies, visited_matches)

                # Remove any matches from skip_condition if they're also direct dependencies
                # (a match can't be both - if it's used in winner/loser, it's direct)
                dependencies["skip_condition"] -= dependencies["direct"]

        # Recursively visit all children
        for child in tree.children:
            self._visit(child, dependencies, visited_matches)

    def _extract_function_name(self, tree) -> str | None:
        """Extract function name from a tree node."""
        if isinstance(tree, Token):
            return tree.value
        if isinstance(tree, Tree):
            if tree.data == "identifier_atom" and tree.children:
                return tree.children[0].value
            elif tree.data == "expression" and tree.children:
                return self._extract_function_name(tree.children[0])
        return None

    def _extract_match_name(self, tree) -> str | None:
        """Extract match name from a match_atom node."""
        if isinstance(tree, Token):
            return None
        if isinstance(tree, Tree):
            if tree.data == "match_atom" and tree.children:
                token = tree.children[0]
                if isinstance(token, Token):
                    # Remove braces
                    return token.value[1:-1]
            elif tree.data == "expression" and tree.children:
                return self._extract_match_name(tree.children[0])
            elif tree.data == "atom" and tree.children:
                return self._extract_match_name(tree.children[0])
        return None

    def _find_all_match_atoms(self, tree, matches: Set[str]):
        """
        Recursively find all match atoms in a tree and add them to the set.
        Also finds match names in team literals like [Match1::winner].

        Args:
            tree: Tree node to search
            matches: Set to accumulate match names
        """
        if isinstance(tree, Token):
            return
        if not isinstance(tree, Tree):
            return

        if tree.data == "match_atom" and tree.children:
            token = tree.children[0]
            if isinstance(token, Token):
                matches.add(token.value[1:-1])  # Remove braces
        elif tree.data == "team_atom" and tree.children:
            # Extract match names from team literals like [Match1::winner] or [Match1::loser]
            token = tree.children[0]
            if isinstance(token, Token):
                team_literal = token.value[1:-1]  # Remove brackets
                # Check if it's a MatchName::winner or MatchName::loser reference
                if "::" in team_literal:
                    parts = team_literal.split("::", 1)
                    if len(parts) == 2:
                        match_name, qualifier = parts
                        if qualifier in {"winner", "loser"}:
                            matches.add(match_name)

        # Recursively visit all children
        for child in tree.children:
            self._find_all_match_atoms(child, matches)

    def _analyze_match_skip_condition(
        self,
        match_name: str,
        dependencies: Dict[str, Set[str]],
        visited_matches: Set[str],
    ):
        """
        Recursively analyze a match's skip condition to find transitive dependencies.

        This method handles transitive dependencies: if match A's skip condition depends on
        match B's skip condition, then match A transitively depends on match B.

        Args:
            match_name: Name of the match whose skip condition to analyze
            dependencies: Dictionary to accumulate dependencies
            visited_matches: Set of matches already being analyzed (for cycle detection)
        """
        try:
            from app.models import Match
            from flask import has_app_context

            # Only query database if we're in an app context
            if not has_app_context():
                return

            # Query the match's skip condition
            match = Match.query.filter_by(name=match_name, event=self.event).first()
            if not match or not match.skip_condition:
                return

            # Analyze the skip condition recursively with cycle detection
            # Pass the visited_matches set to prevent infinite recursion
            skip_cond_deps = self.analyze(match.skip_condition, visited_matches)
            dependencies["direct"].update(skip_cond_deps["direct"])
            dependencies["skip_condition"].update(skip_cond_deps["skip_condition"])
        except Exception:
            # If we can't query the database (e.g., no app context, import errors, etc.),
            # just skip the recursive analysis. The direct dependencies are still found.
            pass
