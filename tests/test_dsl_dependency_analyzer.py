"""
Tests for the DSL dependency analyzer.

Tests the MatchDependencyAnalyzer which analyzes skip-condition expressions
(is-skipped, winner, loser, etc.) to find match dependencies.
"""

import pytest
from app.utils.dsl_dependency_analyzer import MatchDependencyAnalyzer
from app.models import Match, db


class TestMatchDependencyAnalyzer:
    """Test the MatchDependencyAnalyzer class."""

    @pytest.mark.unit
    def test_empty_expression(self, app, tournament):
        """Test that empty expressions return no dependencies."""
        with app.app_context():
            analyzer = MatchDependencyAnalyzer(tournament.url)
            result = analyzer.analyze("")
            assert result["direct"] == set()
            assert result["skip_condition"] == set()

    @pytest.mark.unit
    def test_no_dependencies(self, app, tournament):
        """Test expressions with no match dependencies."""
        with app.app_context():
            analyzer = MatchDependencyAnalyzer(tournament.url)
            result = analyzer.analyze("true")
            assert result["direct"] == set()
            assert result["skip_condition"] == set()

            result = analyzer.analyze("(== 5 5)")
            assert result["direct"] == set()
            assert result["skip_condition"] == set()

    @pytest.mark.unit
    def test_direct_dependency_winner(self, app, tournament):
        """Test direct dependency from winner function."""
        with app.app_context():
            analyzer = MatchDependencyAnalyzer(tournament.url)
            result = analyzer.analyze("(winner {Match1})")
            assert result["direct"] == {"Match1"}
            assert result["skip_condition"] == set()

    @pytest.mark.unit
    def test_direct_dependency_loser(self, app, tournament):
        """Test direct dependency from loser function."""
        with app.app_context():
            analyzer = MatchDependencyAnalyzer(tournament.url)
            result = analyzer.analyze("(loser {Match2})")
            assert result["direct"] == {"Match2"}
            assert result["skip_condition"] == set()

    @pytest.mark.unit
    def test_direct_dependency_points_won(self, app, tournament):
        """Test direct dependency from points-won function."""
        with app.app_context():
            analyzer = MatchDependencyAnalyzer(tournament.url)
            result = analyzer.analyze("(points-won [team1] {Match1})")
            assert result["direct"] == {"Match1"}
            assert result["skip_condition"] == set()

    @pytest.mark.unit
    def test_is_skipped_dependency(self, app, tournament):
        """Test is-skipped dependency."""
        with app.app_context():
            analyzer = MatchDependencyAnalyzer(tournament.url)
            result = analyzer.analyze("(is-skipped {Match2})")
            assert result["direct"] == set()
            assert result["skip_condition"] == {"Match2"}

    @pytest.mark.unit
    def test_complex_expression_with_if(self, app, tournament):
        """Test the complex expression with if statement."""
        with app.app_context():
            analyzer = MatchDependencyAnalyzer(tournament.url)
            expression = "(is-skipped (if (== [teamnamehere] (winner {matchnamehere})) {othermatchname} {othermatchname2}))"
            result = analyzer.analyze(expression)

            # Should have matchnamehere as direct dependency (from winner call)
            assert "matchnamehere" in result["direct"]
            # Should have othermatchname and othermatchname2 as skip_condition dependencies (is-skipped)
            assert "othermatchname" in result["skip_condition"]
            assert "othermatchname2" in result["skip_condition"]
            # matchnamehere should NOT be in skip_condition (it's a direct dependency)
            assert "matchnamehere" not in result["skip_condition"]

    @pytest.mark.unit
    def test_multiple_direct_dependencies(self, app, tournament):
        """Test expression with multiple direct dependencies."""
        with app.app_context():
            analyzer = MatchDependencyAnalyzer(tournament.url)
            result = analyzer.analyze(
                "(and (== 0 (losses [Match1::winner])) (== 0 (losses [Match2::winner])))"
            )
            assert "Match1" in result["direct"]
            assert "Match2" in result["direct"]
            assert result["skip_condition"] == set()

    @pytest.mark.unit
    def test_is_skipped_no_transitive_deps(self, app, tournament):
        """Test that is-skipped does not add transitive skip_condition deps."""
        with app.app_context():
            match1 = Match(
                name="Match1",
                event=tournament.url,
                skip_condition="(is-skipped {Other})",
            )
            match2 = Match(
                name="Match2",
                event=tournament.url,
                skip_condition="(is-skipped {Match1})",
            )
            db.session.add_all([match1, match2])
            db.session.commit()

            analyzer = MatchDependencyAnalyzer(tournament.url)
            # (is-skipped {Match2}) only depends on Match2's status, not Match2's skip_condition
            result = analyzer.analyze("(is-skipped {Match2})")
            assert result["skip_condition"] == {"Match2"}
            assert result["direct"] == set()

    @pytest.mark.unit
    def test_mixed_dependencies(self, app, tournament):
        """Test expression with both direct and skip_condition dependencies."""
        with app.app_context():
            analyzer = MatchDependencyAnalyzer(tournament.url)
            result = analyzer.analyze("(and (winner {Match1}) (is-skipped {Match2}))")
            assert "Match1" in result["direct"]
            assert "Match2" in result["skip_condition"]
            assert "Match1" not in result["skip_condition"]
            assert "Match2" not in result["direct"]

    @pytest.mark.unit
    def test_is_skipped_single_match(self, app, tournament):
        """Test is-skipped with a single match (no recursion)."""
        with app.app_context():
            match1 = Match(
                name="Match1",
                event=tournament.url,
                skip_condition="(is-skipped {Match2})",
            )
            match2 = Match(
                name="Match2",
                event=tournament.url,
                skip_condition="(is-skipped {Match1})",
            )
            db.session.add_all([match1, match2])
            db.session.commit()

            analyzer = MatchDependencyAnalyzer(tournament.url)
            result = analyzer.analyze("(is-skipped {Match1})")
            assert result["skip_condition"] == {"Match1"}
            assert result["direct"] == set()

    @pytest.mark.unit
    def test_match_model_method(self, app, tournament):
        """Test the get_skip_condition_dependencies method on Match model."""
        with app.app_context():
            match = Match(
                name="TestMatch",
                event=tournament.url,
                skip_condition="(is-skipped (if (== [teamnamehere] (winner {matchnamehere})) {othermatchname} {othermatchname2}))",
            )
            db.session.add(match)
            db.session.commit()

            deps = match.get_skip_condition_dependencies()
            assert "matchnamehere" in deps["direct"]
            assert "othermatchname" in deps["skip_condition"]
            assert "othermatchname2" in deps["skip_condition"]
            assert "matchnamehere" not in deps["skip_condition"]

    @pytest.mark.unit
    def test_invalid_expression_handling(self, app, tournament):
        """Test that invalid expressions don't crash the analyzer."""
        with app.app_context():
            analyzer = MatchDependencyAnalyzer(tournament.url)
            # Invalid syntax should return empty dependencies
            result = analyzer.analyze("(invalid syntax here")
            assert result["direct"] == set()
            assert result["skip_condition"] == set()
