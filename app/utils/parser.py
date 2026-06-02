"""
this is a lisp based language with the following simple options:

(wins TEAM) -> INT
(losses TEAM) -> INT
(winner MATCH) -> TEAM
(loser MATCH) -> TEAM
(points-won TEAM MATCH) -> INT
(points-lost TEAM MATCH) -> INT
(points-won TEAM) -> INT
(points-lost TEAM) -> INT
(is-skipped MATCH) -> BOOL

(+ INT INT) -> INT
(- INT INT) -> INT
(* INT INT) -> INT
(/ INT INT) -> INT
(> INT INT) -> BOOL
(< INT INT) -> BOOL
(>= INT INT) -> BOOL
(<= INT INT) -> BOOL
(== ANY ANY) -> BOOL
(or BOOL BOOL) -> BOOL
(and BOOL BOOL) -> BOOL
(not BOOL) -> BOOL

(if COND IF_TRUE IF_FALSE)

(cons *_) -> LIST
(car LIST)
(cdr LIST)
(get INDEX LIST) -> gets val at index or NIL
(or-default VAL DEFAULT) -> returns VAL if VAL is not NIL else DEFAULT
(len LIST) -> INT
(map LIST FUNC)
(reduce LIST FUNC)

(lambda (*args) (output))

(max LIST) -> element
(min LIST) -> element

(max_by LIST FUNC) -> element
(min_by LIST FUNC) -> element


curly braces denote matches. (ie, `{literal match}`)
square braces denote teams. (ie, `[literal team name]`)

data types:
- INT
- NIL
- BOOL
- MATCH
- TEAM
- LIST
- FUNC

"""

import difflib

from lark import Lark, Tree
from lark.exceptions import LarkError, UnexpectedInput
from sqlalchemy import or_, and_
from app.models import Match as MatchDB, Point as PointDB, Team as TeamDB, Tag
from app.domain.enums import WinnerSide


class DSLValidationError(Exception):
    """Raised when DSL expression validation fails."""

    pass


# Bracket pairings that ASS supports.
_BRACKET_PAIRS = {"(": ")", "[": "]", "{": "}"}
_CLOSE_TO_OPEN = {v: k for k, v in _BRACKET_PAIRS.items()}


def _format_position(text: str, pos: int) -> str:
    """Render `(line N, col M)` for a 0-based byte offset into `text`."""
    if pos < 0 or pos > len(text):
        return ""
    line = text.count("\n", 0, pos) + 1
    last_nl = text.rfind("\n", 0, pos)
    col = pos - last_nl  # 1-based when last_nl == -1 because pos - (-1) = pos + 1
    return f"line {line}, col {col}"


def _check_balanced_brackets(text: str) -> None:
    """Lightweight bracket-balance check that points at the offending character.

    ASS uses three nesting kinds — `()`, `[]`, `{}`. Square and curly
    literals don't nest (they enclose names, not sub-expressions), but they
    still need to be paired. We scan once and raise a `DSLValidationError`
    with a position the caller can show in the UI.
    """
    stack: list[tuple[str, int]] = []
    in_team_literal = False
    in_match_literal = False
    for i, c in enumerate(text):
        if in_team_literal:
            if c == "]":
                in_team_literal = False
                stack.pop()
            continue
        if in_match_literal:
            if c == "}":
                in_match_literal = False
                stack.pop()
            continue
        if c == "[":
            if stack and stack[-1][0] == "[":
                raise DSLValidationError(
                    f"Nested '[' at {_format_position(text, i)} — team literals can't contain '['."
                )
            stack.append(("[", i))
            in_team_literal = True
        elif c == "{":
            if stack and stack[-1][0] == "{":
                raise DSLValidationError(
                    f"Nested '{{' at {_format_position(text, i)} — match literals can't contain '{{'."
                )
            stack.append(("{", i))
            in_match_literal = True
        elif c == "(":
            stack.append(("(", i))
        elif c in (")", "]", "}"):
            expected_open = _CLOSE_TO_OPEN[c]
            if not stack:
                raise DSLValidationError(
                    f"Unexpected '{c}' at {_format_position(text, i)} — no matching '{expected_open}' to close."
                )
            open_c, _open_pos = stack[-1]
            if open_c != expected_open:
                raise DSLValidationError(
                    f"Mismatched bracket: '{c}' at {_format_position(text, i)} closes a '{open_c}' opened at {_format_position(text, _open_pos)}."
                )
            stack.pop()
    if stack:
        open_c, open_pos = stack[-1]
        close_c = _BRACKET_PAIRS[open_c]
        raise DSLValidationError(
            f"Unclosed '{open_c}' at {_format_position(text, open_pos)} — expected matching '{close_c}'."
        )


def _suggest_function(name: str, candidates) -> str | None:
    """Return the best fuzzy match for `name` in `candidates`, or None."""
    matches = difflib.get_close_matches(name, list(candidates), n=1, cutoff=0.6)
    return matches[0] if matches else None


# Return-type tables for the parser's built-in functions. A return type is a `frozenset`
# of type-name strings; functions whose return type is fully determined by argument types
# (e.g. `if`, `or-default`) are not in these tables — they're handled in `_infer_types`.
_RETURN_TYPE_FIXED: dict[str, frozenset[str]] = {
    "wins": frozenset({"INT"}),
    "losses": frozenset({"INT"}),
    "points-won": frozenset({"INT"}),
    "points-lost": frozenset({"INT"}),
    "+": frozenset({"INT"}),
    "-": frozenset({"INT"}),
    "*": frozenset({"INT"}),
    "/": frozenset({"INT"}),
    "len": frozenset({"INT"}),
    "==": frozenset({"BOOL"}),
    ">": frozenset({"BOOL"}),
    "<": frozenset({"BOOL"}),
    ">=": frozenset({"BOOL"}),
    "<=": frozenset({"BOOL"}),
    "or": frozenset({"BOOL"}),
    "and": frozenset({"BOOL"}),
    "not": frozenset({"BOOL"}),
    "is-skipped": frozenset({"BOOL"}),
    "winner": frozenset({"TEAM"}),
    "loser": frozenset({"TEAM"}),
    "cons": frozenset({"LIST"}),
    "cdr": frozenset({"LIST"}),
    "map": frozenset({"LIST"}),
    "lambda": frozenset({"FUNC"}),
}


def _infer_list_element_types(lst) -> frozenset[str]:
    """Infer the union of element types in a list-valued expression.

    Handles both already-evaluated data lists (e.g. `[True, False, True]` from
    a fully-concrete `cons`) and preserved `cons` expressions (`["cons", ...]`).
    Returns `{"UNKNOWN"}` for anything else (e.g. a `map` preserved expression),
    since the per-element type isn't visible without evaluating.
    """
    if isinstance(lst, list):
        if lst and isinstance(lst[0], str):
            if lst[0] == "cons":
                elements = lst[1:]
            else:
                return frozenset({"UNKNOWN"})
        else:
            elements = lst
        if not elements:
            return frozenset({"UNKNOWN"})
        types: frozenset[str] = frozenset()
        for elem in elements:
            types |= _infer_types(elem)
        return types
    return frozenset({"UNKNOWN"})


def _infer_types(value) -> frozenset[str]:
    """Infer the set of possible types of an interpreted DSL value.

    Concrete values map directly. Preserved expressions (lists starting with a
    function name) dispatch on the head: most functions have a fixed return type;
    the few whose result type depends on their args (`if`, `or-default`, `get`,
    `car`, `reduce`, `max`/`min`/`max-by`/`min-by`) recurse into their branches
    and union the possibilities.

    Returns `frozenset({"UNKNOWN"})` when nothing better can be said — callers
    should treat that as "don't enforce a type constraint".
    """
    # Order matters: bool is a subclass of int, so check bool first.
    if isinstance(value, bool):
        return frozenset({"BOOL"})
    if isinstance(value, int):
        return frozenset({"INT"})
    if value is None:
        return frozenset({"NIL"})
    if isinstance(value, (Team, SymbolicTeam)):
        return frozenset({"TEAM"})
    if isinstance(value, (Match, SymbolicMatch)):
        return frozenset({"MATCH"})
    if isinstance(value, Lambda):
        return frozenset({"FUNC"})
    if isinstance(value, list):
        # Distinguish a preserved expression (head is a function-name string) from a
        # plain data list. `cons` produces a data list of varied content.
        if value and isinstance(value[0], str):
            head = value[0]
            args = value[1:]
            if head in _RETURN_TYPE_FIXED:
                return _RETURN_TYPE_FIXED[head]
            if head == "if":
                # (if cond then else) — type is union of the two branches.
                if len(args) >= 3:
                    return _infer_types(args[1]) | _infer_types(args[2])
                return frozenset({"UNKNOWN"})
            if head == "or-default":
                # (or-default val default) — val if non-nil, else default; union them
                # but exclude NIL from the val side since or-default falls through.
                if len(args) >= 2:
                    val_types = _infer_types(args[0]) - {"NIL"}
                    return val_types | _infer_types(args[1])
                return frozenset({"UNKNOWN"})
            if head == "get":
                # (get index list) — union of element types in the list, plus NIL for out-of-bounds.
                if len(args) >= 2:
                    return _infer_list_element_types(args[1]) | {"NIL"}
                return frozenset({"UNKNOWN", "NIL"})
            if head == "car":
                # First element of a list — element types of the underlying list if we can see them.
                if len(args) >= 1:
                    return _infer_list_element_types(args[0])
                return frozenset({"UNKNOWN"})
            if head == "reduce":
                return frozenset({"UNKNOWN"})
            if head in ("max", "min", "max-by", "min-by"):
                return frozenset({"UNKNOWN"})
            return frozenset({"UNKNOWN"})
        # Plain data list (cons output, or similar).
        return frozenset({"LIST"})
    return frozenset({"UNKNOWN"})


class Lambda:
    """Represents a lambda function closure."""

    def __init__(self, params, body_tree, env, parse_team_literal, parse_match_literal):
        """
        Args:
            params: List of parameter names (or list with single element for variadic)
            body_tree: The body as a Lark Tree node (unevaluated)
            env: The environment (dict) at the time of lambda creation
            parse_team_literal: Function to parse team literals
            parse_match_literal: Function to parse match literals
        """
        self.params = params
        self.body_tree = body_tree  # Store as Tree node, not evaluated
        self.env = env.copy() if env else {}
        self.parse_team_literal = parse_team_literal
        self.parse_match_literal = parse_match_literal

    def __repr__(self):
        return f"Lambda({self.params}, ...)"


class SymbolicTeam:
    """Symbolic representation of an unresolved team reference."""

    def __init__(self, literal: str, event: str):
        self.literal = literal
        self.url = event

    def __hash__(self):
        return hash((self.url, self.literal))

    def __repr__(self):
        return f"SymbolicTeam([{self.literal}])"


class SymbolicMatch:
    """Symbolic representation of an unresolved match reference."""

    def __init__(self, literal: str, event: str):
        self.literal = literal
        self.url = event

    def __hash__(self):
        return hash((self.url, self.literal))

    def __repr__(self):
        return f"SymbolicMatch({{{self.literal}}})"


def parse_team_literal(literal: str, event: str):
    """parse team literal into Team object or SymbolicTeam if not found. parses tags and match winners/losers just like normal options for team references.

    Args:
        literal (str): literal inside of square brackets
        event (str): tournament url
    Returns:
        Team | SymbolicTeam: team object or symbolic representation
    """
    if "::" not in literal:
        team_obj = TeamDB.query.filter_by(id=literal).first()
        if team_obj:
            return Team(team_obj, event)
        return SymbolicTeam(literal, event)
    else:
        split = literal.split("::")
        assert len(split) == 2, f"Invalid team literal: {literal}"
        match_name, qualifier = split
        if qualifier == "winner":
            match_obj = MatchDB.query.filter_by(name=match_name, event=event).first()
            if not match_obj:
                raise DSLValidationError(f"Match {match_name} not found")
            return Match(match_obj, event).winner()
        elif qualifier == "loser":
            match_obj = MatchDB.query.filter_by(name=match_name, event=event).first()
            if not match_obj:
                raise DSLValidationError(f"Match {match_name} not found")
            return Match(match_obj, event).loser()
        elif match_name == "tag":
            tag = Tag.query.filter_by(name=qualifier, event=event).first()
            if not tag:
                known = [t.name for t in Tag.query.filter_by(event=event).all()]
                suggestion = _suggest_function(qualifier, known)
                hint = f" Did you mean 'tag::{suggestion}'?" if suggestion else ""
                raise DSLValidationError(f"Tag '{qualifier}' does not exist.{hint}")
            if not tag.team:
                # Tag exists but its team isn't assigned yet — stay symbolic.
                return SymbolicTeam(literal, event)
            team_obj = TeamDB.query.filter_by(id=tag.team).first()
            if team_obj:
                return Team(team_obj, event)
            # Tag's team id refers to a deleted team — stay symbolic.
            return SymbolicTeam(literal, event)
        else:
            raise DSLValidationError(f"Invalid team literal: {literal}")


def parse_match_literal(literal: str, event: str):
    """parse match literal into Match object or SymbolicMatch if not found.

    Args:
        literal (str): literal inside of curly braces
        event (str): tournament url
    Returns:
        Match | SymbolicMatch: match object or symbolic representation
    """
    obj = MatchDB.query.filter_by(name=literal, event=event).first()
    if not obj:
        return SymbolicMatch(literal, event)
    return Match(obj, event)


class Team:
    def __init__(self, obj: TeamDB, event: str):
        self.url = event
        self.obj = obj

    def points_won(self, m=None):
        # Filter Point columns first (before join) to reduce join set
        query = PointDB.query.filter(PointDB.rerolled == False)
        if m is not None:
            query = query.filter(PointDB.match == m.obj.uuid)
        # Then join and filter on Match columns
        query = query.join(MatchDB, PointDB.match == MatchDB.uuid).filter(
            MatchDB.event == self.url,
            or_(
                and_(MatchDB.team1 == self.obj.id, PointDB.winner == WinnerSide.TEAM1),
                and_(MatchDB.team2 == self.obj.id, PointDB.winner == WinnerSide.TEAM2),
            ),
        )
        return query.count()

    def points_lost(self, m=None):
        query = PointDB.query.filter(PointDB.rerolled == False)
        if m is not None:
            query = query.filter(PointDB.match == m.obj.uuid)
        query = query.join(MatchDB, PointDB.match == MatchDB.uuid).filter(
            MatchDB.event == self.url,
            or_(
                and_(MatchDB.team1 == self.obj.id, PointDB.winner == WinnerSide.TEAM2),
                and_(MatchDB.team2 == self.obj.id, PointDB.winner == WinnerSide.TEAM1),
            ),
        )
        return query.count()

    def wins(self):
        return (
            MatchDB.query.filter_by(event=self.url, team1=self.obj.id, match_winner=WinnerSide.TEAM1).count()
            + MatchDB.query.filter_by(event=self.url, team2=self.obj.id, match_winner=WinnerSide.TEAM2).count()
        )

    def losses(self):
        return (
            MatchDB.query.filter_by(event=self.url, team1=self.obj.id, match_winner=WinnerSide.TEAM2).count()
            + MatchDB.query.filter_by(event=self.url, team2=self.obj.id, match_winner=WinnerSide.TEAM1).count()
        )

    def __hash__(self):
        return hash((self.url, self.obj.id))


class Match:
    def __init__(self, obj: MatchDB, event: str):
        self.url = event
        self.obj = obj

    def winner(self):
        winner = self.obj.winner_team_id
        if winner is None:
            # Return symbolic representation instead of None
            return SymbolicTeam(f"{self.obj.name}::winner", self.url)
        team_obj = TeamDB.query.filter_by(id=winner).first()
        if team_obj:
            return Team(team_obj, self.url)
        return SymbolicTeam(winner, self.url)

    def loser(self):
        loser = self.obj.loser_team_id
        if loser is None:
            # Return symbolic representation instead of None
            return SymbolicTeam(f"{self.obj.name}::loser", self.url)
        team_obj = TeamDB.query.filter_by(id=loser).first()
        if team_obj:
            return Team(team_obj, self.url)
        return SymbolicTeam(loser, self.url)

    def __hash__(self):
        return hash((self.url, self.obj.uuid))


class Simplifier:
    """Evaluates DSL expressions by executing code and resolving symbols."""

    # Built-in function names that are valid identifiers
    BUILTINS = {
        "if",
        "lambda",
        "cons",
        "car",
        "cdr",
        "get",
        "or-default",
        "len",
        "map",
        "reduce",
        "max",
        "min",
        "max-by",
        "min-by",
        "+",
        "-",
        "*",
        "/",
        ">",
        "<",
        ">=",
        "<=",
        "==",
        "or",
        "and",
        "not",
        "wins",
        "losses",
        "winner",
        "loser",
        "points-won",
        "points-lost",
        "is-skipped",
    }

    def __init__(self, parse_team_literal, parse_match_literal, env=None):
        self.parse_team_literal = parse_team_literal
        self.parse_match_literal = parse_match_literal
        self.env = env if env is not None else {}

    def visit(self, tree):
        """Top-down visitor - dispatches to appropriate method based on tree.data."""
        if not isinstance(tree, Tree):
            return tree

        method_name = tree.data
        if hasattr(self, method_name):
            method = getattr(self, method_name)
            return method(tree)
        else:
            # Default: visit children
            return self.visit_children(tree)

    def visit_children(self, tree):
        """Visit all children of a tree node."""
        return [self.visit(child) for child in tree.children]

    def _resolve_identifier(self, value):
        """Resolve an identifier from environment if it's a string."""
        if isinstance(value, str):
            if value in self.env:
                return self.env[value]
            elif value in self.BUILTINS:
                return value  # Built-in function name
        return value

    def _visit_params_list(self, tree):
        """Visit a parameter list, ensuring it returns a list of parameter names.

        For lambda parameters like (x) or (x y), we want to return ["x"] or ["x", "y"].
        This handles the case where (x) is a single-element list that should stay as a list.
        """
        if not isinstance(tree, Tree) or tree.data != "list":
            # Not a list - error
            raise DSLValidationError("Lambda parameters must be a list")

        if not tree.children:
            return []  # Empty parameter list

        # Visit all children (they should be identifiers)
        params = []
        for child in tree.children:
            param = self.visit(child)
            # Parameters should be identifiers (strings)
            if isinstance(param, str):
                params.append(param)
            else:
                raise DSLValidationError(f"Lambda parameter names must be identifiers, got {type(param).__name__}")

        return params

    def _is_preserved_expression(self, value):
        """Check if a value is a preserved expression (list starting with function name)."""
        return isinstance(value, list) and len(value) > 0 and isinstance(value[0], str)

    def _validate_arg_count(self, head, args, expected_count, optional_count=0):
        """Validate argument count. Raises DSLValidationError if invalid."""
        min_count = expected_count - optional_count
        max_count = expected_count
        actual_count = len(args)
        if actual_count < min_count or actual_count > max_count:
            raise DSLValidationError(f"({head} ...) expects {expected_count} argument(s), got {actual_count}")

    def _validate_type(self, value, expected_type, type_name, arg_position, allow_none=False):
        """Validate argument type. Raises DSLValidationError if invalid.

        Args:
            value: The value to validate
            expected_type: Expected type ("TEAM", "MATCH", "INT", "BOOL", "LIST", "ANY")
            type_name: Human-readable type name for error messages
            arg_position: Argument position (1-indexed) for error messages
            allow_none: If True, None values are allowed (for unresolved references)
        """
        # Allow None if explicitly allowed (for unresolved references that can't be simplified yet)
        if allow_none and value is None:
            return

        if expected_type == "TEAM":
            if not isinstance(value, Team):
                raise DSLValidationError(f"Argument {arg_position} must be a TEAM, got {type(value).__name__}")
        elif expected_type == "MATCH":
            if not isinstance(value, Match):
                raise DSLValidationError(f"Argument {arg_position} must be a MATCH, got {type(value).__name__}")
        elif expected_type == "INT":
            if not isinstance(value, int):
                raise DSLValidationError(f"Argument {arg_position} must be an INT, got {type(value).__name__}")
        elif expected_type == "BOOL":
            if not isinstance(value, bool):
                raise DSLValidationError(f"Argument {arg_position} must be a BOOL, got {type(value).__name__}")
        elif expected_type == "LIST":
            if not isinstance(value, list):
                raise DSLValidationError(f"Argument {arg_position} must be a LIST, got {type(value).__name__}")
        elif expected_type == "ANY":
            pass  # No validation needed

    # Interpreter methods - top-down traversal with explicit control

    def expression(self, tree):
        """Visit expression node - just visit the child."""
        if tree.children:
            return self.visit(tree.children[0])
        return None

    # Atom transformations
    def int_atom(self, tree):
        token = tree.children[0]
        return int(token.value)

    def bool_atom(self, tree):
        token = tree.children[0]
        return token.value == "true"

    def nil_atom(self, tree):
        return None

    def team_atom(self, tree):
        token = tree.children[0]
        team_str = token.value[1:-1]  # Remove brackets
        return self.parse_team_literal(team_str)

    def match_atom(self, tree):
        token = tree.children[0]
        match_str = token.value[1:-1]  # Remove braces
        return self.parse_match_literal(match_str)

    def identifier_atom(self, tree):
        """Resolve identifier to variable value or return as string."""
        token = tree.children[0]
        name = token.value
        # Handle boolean and nil literals (fallback)
        if name == "true":
            return True
        if name == "false":
            return False
        if name == "nil":
            return None
        # Check if it's in the environment (lambda argument or closure variable)
        if name in self.env:
            return self.env[name]
        # Check if it's a built-in function name
        if name in self.BUILTINS:
            return name  # Return as string for function calls
        # Unknown symbol - return as string (will be resolved/error later)
        return name

    # Main expression handling
    def list(self, tree):
        """Process a list/s-expression with top-down control."""
        if not tree.children:
            return []  # Empty list

        # Evaluate head first (top-down: check what we're calling before evaluating args)
        head_tree = tree.children[0]
        head = self.visit(head_tree)
        head = self._resolve_identifier(head)

        # Handle lambda special form - DON'T evaluate the body
        if isinstance(head, str) and head == "lambda":
            if len(tree.children) != 3:
                raise DSLValidationError("lambda expects 2 arguments: (params) and body")

            # Evaluate params (second child) - this should be a list like (x) or (x y)
            params_tree = tree.children[1]
            # For params, we need to visit it but ensure it returns a list
            # If it's a single-element list like (x), we want ["x"]
            params_expr = self._visit_params_list(params_tree)
            if not isinstance(params_expr, list):
                raise DSLValidationError("Lambda parameters must be a list")

            # DON'T evaluate body (third child) - store the Tree node
            body_tree = tree.children[2]
            return self._evaluate_lambda(head, params_expr, body_tree)

        # Handle if special form - evaluate condition first, then choose branch
        if isinstance(head, str) and head == "if":
            if len(tree.children) != 4:
                raise DSLValidationError("if expects 3 arguments: condition, if_true, if_false")

            # Evaluate condition
            cond_tree = tree.children[1]
            cond = self.visit(cond_tree)
            cond = self._resolve_identifier(cond)

            # Evaluate appropriate branch based on condition
            if isinstance(cond, bool):
                branch_tree = tree.children[2] if cond else tree.children[3]
                return self.visit(branch_tree)
            else:
                # Condition is symbolic or not boolean - preserve expression
                if_true = self.visit(tree.children[2])
                if_false = self.visit(tree.children[3])
                return [head, cond, if_true, if_false]

        # Regular function call - evaluate all arguments
        args = []
        for child in tree.children[1:]:
            arg = self.visit(child)
            # If argument is a single-element list like [10], unwrap it
            # This handles cases where a value is parsed as (value) instead of just value
            if isinstance(arg, list) and len(arg) == 1:
                # Check if it's a data list (not a preserved expression)
                if not self._is_preserved_expression(arg):
                    # Unwrap the single element
                    arg = arg[0]
            args.append(arg)

        # Resolve all arguments (they might be identifiers)
        args = [self._resolve_identifier(arg) for arg in args]

        # If head is a Lambda, call it
        if isinstance(head, Lambda):
            return self._call_lambda(head, args)

        # If head is a string (identifier), check if it's a function call
        if isinstance(head, str):
            # Handle built-in functions
            if head == "cons":
                return self._evaluate_cons(head, args)
            elif head == "car":
                return self._evaluate_car(head, args)
            elif head == "cdr":
                return self._evaluate_cdr(head, args)
            elif head == "get":
                return self._evaluate_get(head, args)
            elif head == "or-default":
                return self._evaluate_or_default(head, args)
            elif head == "len":
                return self._evaluate_len(head, args)
            elif head == "map":
                return self._evaluate_map(head, args)
            elif head == "reduce":
                return self._evaluate_reduce(head, args)
            elif head == "max":
                return self._evaluate_max(head, args)
            elif head == "min":
                return self._evaluate_min(head, args)
            elif head == "max-by":
                return self._evaluate_max_by(head, args)
            elif head == "min-by":
                return self._evaluate_min_by(head, args)
            # Handle arithmetic and comparison operators
            elif head in {"+", "-", "*", "/", ">", "<", ">=", "<=", "=="}:
                return self._evaluate_binary_op(head, args)
            elif head in {"or", "and", "not"}:
                return self._evaluate_logical_op(head, args)
            # Handle team/match operations
            elif head == "wins":
                return self._evaluate_wins(head, args)
            elif head == "losses":
                return self._evaluate_losses(head, args)
            elif head == "winner":
                return self._evaluate_winner(head, args)
            elif head == "loser":
                return self._evaluate_loser(head, args)
            elif head == "points-won":
                return self._evaluate_points_won(head, args)
            elif head == "points-lost":
                return self._evaluate_points_lost(head, args)
            elif head == "is-skipped":
                return self._evaluate_is_skipped(head, args)
            else:
                # Unknown function name — try did-you-mean from the builtin set + bound env names.
                known = set(self.BUILTINS) | set(self.env.keys())
                suggestion = _suggest_function(head, known)
                if suggestion:
                    raise DSLValidationError(f"Unknown function '{head}'. Did you mean '{suggestion}'?")
                raise DSLValidationError(f"Unknown function '{head}'.")

        # If head is not a string or lambda, it's an error
        raise DSLValidationError(f"Cannot call {type(head).__name__} as a function")

    # Lambda evaluation
    def _call_lambda(self, lambda_func, args):
        """Call a lambda function with arguments."""
        if not isinstance(lambda_func, Lambda):
            raise DSLValidationError(f"Expected Lambda, got {type(lambda_func).__name__}")

        # Create new environment with closure
        new_env = lambda_func.env.copy()

        # Validate argument count
        if len(args) != len(lambda_func.params):
            raise DSLValidationError(f"Lambda expects {len(lambda_func.params)} argument(s), got {len(args)}")

        # Bind arguments to parameters
        for param, arg in zip(lambda_func.params, args):
            new_env[param] = arg

        # Evaluate body in new environment by visiting the Tree node
        # Create a new simplifier with the new environment
        simplifier = Simplifier(lambda_func.parse_team_literal, lambda_func.parse_match_literal, env=new_env)
        # Visit the Tree node with the new environment
        result = simplifier.visit(lambda_func.body_tree)

        # Special case: if body is a single-element list like (x) containing just an identifier,
        # unwrap it to return the identifier's value
        # This handles cases like ((lambda (x) x) 42) where body is just x
        if isinstance(result, list) and len(result) == 1:
            single_elem = result[0]
            # If it's a string identifier that's in the environment, return its value
            if isinstance(single_elem, str) and single_elem in new_env:
                return new_env[single_elem]
            # If it's a string that's not a builtin and not in env, it's an unresolved identifier
            # Keep it as a list for now (will error later if used as function)
            # But if it's resolved to a value, we can unwrap
            if not isinstance(single_elem, str):
                # It's already a value, unwrap it
                return single_elem

        return result

    def _evaluate_value(self, value):
        """Evaluate a single value, resolving identifiers from environment."""
        if isinstance(value, str):
            # Check if it's an identifier in the environment
            if value in self.env:
                return self.env[value]
            elif value in self.BUILTINS:
                return value  # Built-in function name
            else:
                # Identifier not found - return as string for now
                return value
        elif isinstance(value, list):
            # Could be a function call, preserved expression, or data list
            if not value:
                return []
            # Check if it's a preserved expression (starts with function name)
            if self._is_preserved_expression(value):
                return value  # Return as-is, it's already preserved
            # Check if it looks like a function call (first element is a string or Lambda)
            # vs a data list (first element is not a string/Lambda)
            if len(value) > 0:
                first = value[0]
                # If first element is a string (function name) or Lambda, it's a function call
                if isinstance(first, (str, Lambda)):
                    return self.list(value)
                # Otherwise, it's a data list - return as-is
                return value
            return value
        else:
            # Literal value (int, bool, None, Team, Match, Lambda, etc.)
            return value

    def _evaluate_lambda(self, head, params_expr, body_tree):
        """Evaluate (lambda (params) body) expression.

        Args:
            head: The function name ("lambda")
            params_expr: List of parameter name strings (not evaluated)
            body_tree: The body as a Lark Tree node (unevaluated)
        """
        # Parse parameters - params_expr should be a list of strings (parameter names)
        if not isinstance(params_expr, list):
            raise DSLValidationError("Lambda parameters must be a list")

        # Check for variadic (*args) syntax
        if len(params_expr) == 1 and isinstance(params_expr[0], str) and params_expr[0].startswith("*"):
            # Variadic parameter
            param_name = params_expr[0][1:]  # Remove *
            params = [param_name]
        else:
            # Fixed parameters - extract parameter names
            params = []
            for p in params_expr:
                # Parameter names should be strings (identifiers)
                if isinstance(p, str):
                    params.append(p)
                else:
                    # If it was evaluated to something else, that's an error
                    raise DSLValidationError(f"Lambda parameter names must be identifiers, got {type(p).__name__}")

        # Create lambda closure with current environment, storing the Tree node
        lambda_obj = Lambda(
            params,
            body_tree,
            self.env,
            self.parse_team_literal,
            self.parse_match_literal,
        )
        return lambda_obj

    # Helper methods for evaluation

    def _evaluate_binary_op(self, op, args):
        """Evaluate binary operations."""
        self._validate_arg_count(op, args, 2)
        a, b = args

        # Check for symbolic values or preserved expressions (lists) - preserve expression if found
        # But distinguish between data lists (like [1, 2, 3]) and preserved expressions (like ['+', x, y])
        if isinstance(a, (SymbolicTeam, SymbolicMatch)) or isinstance(b, (SymbolicTeam, SymbolicMatch)):
            return [op, a, b]
        # Check if it's a preserved expression (starts with function name) vs a data list
        # Preserved expressions are lists that start with a function name (string)
        if isinstance(a, list):
            if self._is_preserved_expression(a):
                return [op, a, b]
            # It's a data list - can't do arithmetic on it
            raise DSLValidationError(f"Argument 1 of ({op} ...) must be an INT, got LIST")
        if isinstance(b, list):
            if self._is_preserved_expression(b):
                return [op, a, b]
            # It's a data list - can't do arithmetic on it
            raise DSLValidationError(f"Argument 2 of ({op} ...) must be an INT, got LIST")

        # Check for unresolved identifiers (strings that aren't builtins or in environment)
        # These might be lambda parameters that will be resolved when the lambda is called
        if isinstance(a, str) and a not in self.BUILTINS and a not in self.env:
            return [op, a, b]
        if isinstance(b, str) and b not in self.BUILTINS and b not in self.env:
            return [op, a, b]

        # Arithmetic and comparison operators require integers
        # Note: bool is a subclass of int in Python, so we need to check type explicitly
        if op in {"+", "-", "*", "/", ">", "<", ">=", "<="}:
            if type(a) is not int:  # Use 'is' to check exact type, not isinstance
                raise DSLValidationError(f"Argument 1 of ({op} ...) must be an INT, got {type(a).__name__}")
            if type(b) is not int:  # Use 'is' to check exact type, not isinstance
                raise DSLValidationError(f"Argument 2 of ({op} ...) must be an INT, got {type(b).__name__}")
            if op == "+":
                return a + b
            elif op == "-":
                return a - b
            elif op == "*":
                return a * b
            elif op == "/":
                if b == 0:
                    raise DSLValidationError("Division by zero")
                return a // b
            elif op == ">":
                return a > b
            elif op == "<":
                return a < b
            elif op == ">=":
                return a >= b
            elif op == "<=":
                return a <= b
        elif op == "==":
            # == works on any comparable values
            if isinstance(a, (int, bool, type(None))) and isinstance(b, (int, bool, type(None))):
                return a == b
            # For team objects, compare by team id (same team can be produced by different code paths)
            elif isinstance(a, Team) and isinstance(b, Team):
                return a.obj.id == b.obj.id
            elif isinstance(a, Match) and isinstance(b, Match):
                return a.obj.uuid == b.obj.uuid
            else:
                # Can't compare different types - preserve expression instead of returning False
                return [op, a, b]

    def _evaluate_logical_op(self, op, args):
        """Evaluate logical operations."""
        if op == "not":
            self._validate_arg_count(op, args, 1)
            (a,) = args
            if isinstance(a, (SymbolicTeam, SymbolicMatch, list)):
                return [op, a]
            a_bool = a is not None and a is not False
            return not a_bool

        self._validate_arg_count(op, args, 2)
        a, b = args

        # Check for symbolic values or preserved expressions - preserve if found
        if isinstance(a, (SymbolicTeam, SymbolicMatch)) or isinstance(b, (SymbolicTeam, SymbolicMatch)):
            return [op, a, b]
        if isinstance(a, list) or isinstance(b, list):
            # One of the operands is a preserved expression
            return [op, a, b]

        # Convert to boolean for logical operations
        # In Lisp-like languages, anything non-nil is truthy
        a_bool = a is not None and a is not False
        b_bool = b is not None and b is not False

        if op == "or":
            return a_bool or b_bool
        elif op == "and":
            return a_bool and b_bool
        else:
            raise DSLValidationError(f"Unknown logical operator: {op}")

    def _evaluate_wins(self, head, args):
        """Evaluate (wins TEAM) expression."""
        self._validate_arg_count(head, args, 1)
        team = args[0]
        if isinstance(team, SymbolicTeam):
            # Can't evaluate, preserve expression
            return [head, team]
        if not isinstance(team, Team):
            raise DSLValidationError(f"Argument 1 must be a TEAM, got {type(team).__name__}")
        return team.wins()

    def _evaluate_losses(self, head, args):
        """Evaluate (losses TEAM) expression."""
        self._validate_arg_count(head, args, 1)
        team = args[0]
        if isinstance(team, SymbolicTeam):
            # Can't evaluate, preserve expression
            return [head, team]
        if not isinstance(team, Team):
            raise DSLValidationError(f"Argument 1 must be a TEAM, got {type(team).__name__}")
        return team.losses()

    def _evaluate_winner(self, head, args):
        """Evaluate (winner MATCH) expression."""
        self._validate_arg_count(head, args, 1)
        match = args[0]
        if isinstance(match, SymbolicMatch):
            # Can't evaluate, preserve expression
            return [head, match]
        if not isinstance(match, Match):
            raise DSLValidationError(f"Argument 1 must be a MATCH, got {type(match).__name__}")
        winner = match.winner()
        # winner() returns SymbolicTeam if unknown, which is fine
        return winner

    def _evaluate_loser(self, head, args):
        """Evaluate (loser MATCH) expression."""
        self._validate_arg_count(head, args, 1)
        match = args[0]
        if isinstance(match, SymbolicMatch):
            # Can't evaluate, preserve expression
            return [head, match]
        if not isinstance(match, Match):
            raise DSLValidationError(f"Argument 1 must be a MATCH, got {type(match).__name__}")
        loser = match.loser()
        # loser() returns SymbolicTeam if unknown, which is fine
        return loser

    def _evaluate_points_won(self, head, args):
        """Evaluate (points-won TEAM MATCH?) expression."""
        if len(args) == 1:
            # (points-won TEAM)
            team = args[0]
            if isinstance(team, SymbolicTeam):
                # Can't evaluate, preserve expression
                return [head, team]
            if not isinstance(team, Team):
                raise DSLValidationError(f"Argument 1 must be a TEAM, got {type(team).__name__}")
            return team.points_won()
        elif len(args) == 2:
            # (points-won TEAM MATCH)
            team, match = args
            if isinstance(team, SymbolicTeam) or isinstance(match, SymbolicMatch):
                # Can't evaluate, preserve expression
                return [head, team, match]
            if not isinstance(team, Team):
                raise DSLValidationError(f"Argument 1 must be a TEAM, got {type(team).__name__}")
            if not isinstance(match, Match):
                raise DSLValidationError(f"Argument 2 must be a MATCH, got {type(match).__name__}")
            return team.points_won(match)
        else:
            raise DSLValidationError(f"({head} ...) expects 1 or 2 arguments, got {len(args)}")

    def _evaluate_points_lost(self, head, args):
        """Evaluate (points-lost TEAM MATCH?) expression."""
        if len(args) == 1:
            # (points-lost TEAM)
            team = args[0]
            if isinstance(team, SymbolicTeam):
                # Can't evaluate, preserve expression
                return [head, team]
            if not isinstance(team, Team):
                raise DSLValidationError(f"Argument 1 must be a TEAM, got {type(team).__name__}")
            return team.points_lost()
        elif len(args) == 2:
            # (points-lost TEAM MATCH)
            team, match = args
            if isinstance(team, SymbolicTeam) or isinstance(match, SymbolicMatch):
                # Can't evaluate, preserve expression
                return [head, team, match]
            if not isinstance(team, Team):
                raise DSLValidationError(f"Argument 1 must be a TEAM, got {type(team).__name__}")
            if not isinstance(match, Match):
                raise DSLValidationError(f"Argument 2 must be a MATCH, got {type(match).__name__}")
            return team.points_lost(match)
        else:
            raise DSLValidationError(f"({head} ...) expects 1 or 2 arguments, got {len(args)}")

    def _evaluate_is_skipped(self, head, args):
        """Evaluate (is-skipped MATCH) expression.

        Returns True if match status is SKIPPED, False if IN_PROGRESS or COMPLETED,
        otherwise stays symbolic (NOT_STARTED, TIME_FINALIZED, READY_TO_START).
        """
        from app.domain.enums import MatchStatus

        self._validate_arg_count(head, args, 1)
        match = args[0]
        if not isinstance(match, Match):
            return [head, match]  # Can't simplify if match is not resolved

        status = getattr(match.obj, "status", None)
        if status is None:
            return [head, match]  # Stay symbolic

        # Normalize to string for comparison (DB may store as enum or string)
        status_str = str(status) if status else None
        if status_str == MatchStatus.SKIPPED:
            return True
        if status_str in (MatchStatus.IN_PROGRESS, MatchStatus.COMPLETED):
            return False
        # NOT_STARTED, TIME_FINALIZED, READY_TO_START: stay symbolic
        return [head, match]

    def _evaluate_cons(self, head, args):
        """Evaluate (cons ...) expression - creates a list from arguments."""
        # Check if any argument is a preserved expression
        for arg in args:
            if self._is_preserved_expression(arg) or isinstance(arg, (SymbolicTeam, SymbolicMatch)):
                return [head] + args
        return list(args)

    def _evaluate_car(self, head, args):
        """Evaluate (car LIST) expression."""
        self._validate_arg_count(head, args, 1)
        lst = args[0]
        # Check if it's a preserved expression
        if self._is_preserved_expression(lst):
            return [head, lst]
        if not isinstance(lst, list):
            raise DSLValidationError(f"Argument 1 must be a LIST, got {type(lst).__name__}")
        if not lst:
            raise DSLValidationError("Cannot take car of empty list")
        return lst[0]

    def _evaluate_cdr(self, head, args):
        """Evaluate (cdr LIST) expression."""
        self._validate_arg_count(head, args, 1)
        lst = args[0]
        # Check if it's a preserved expression
        if self._is_preserved_expression(lst):
            return [head, lst]
        if not isinstance(lst, list):
            raise DSLValidationError(f"Argument 1 must be a LIST, got {type(lst).__name__}")
        if not lst:
            raise DSLValidationError("Cannot take cdr of empty list")
        return lst[1:]

    def _evaluate_get(self, head, args):
        """Evaluate (get INDEX LIST) expression."""
        self._validate_arg_count(head, args, 2)
        index, lst = args
        # Check if index or list is a preserved expression
        if self._is_preserved_expression(index) or self._is_preserved_expression(lst):
            return [head, index, lst]
        if not isinstance(index, int):
            raise DSLValidationError(f"Argument 1 must be an INT, got {type(index).__name__}")
        if not isinstance(lst, list):
            raise DSLValidationError(f"Argument 2 must be a LIST, got {type(lst).__name__}")
        if 0 <= index < len(lst):
            return lst[index]
        else:
            # Out of bounds - return None (NIL) as this is a valid result
            return None

    def _evaluate_or_default(self, head, args):
        """Evaluate (or-default VAL DEFAULT) expression."""
        self._validate_arg_count(head, args, 2)
        val, default = args
        # Check if either argument is a preserved expression
        if self._is_preserved_expression(val) or self._is_preserved_expression(default):
            return [head, val, default]
        # No type validation - accepts any types
        if val is not None:  # NIL is represented as None
            return val
        return default

    def _evaluate_len(self, head, args):
        """Evaluate (len LIST) expression."""
        self._validate_arg_count(head, args, 1)
        lst = args[0]
        # Check if it's a preserved expression
        if self._is_preserved_expression(lst):
            return [head, lst]
        if not isinstance(lst, list):
            raise DSLValidationError(f"Argument 1 must be a LIST, got {type(lst).__name__}")
        return len(lst)

    def _evaluate_max(self, head, args):
        """Evaluate (max LIST) expression."""
        self._validate_arg_count(head, args, 1)
        lst = args[0]
        # Check if it's a preserved expression
        if self._is_preserved_expression(lst):
            return [head, lst]
        if not isinstance(lst, list):
            raise DSLValidationError(f"Argument 1 must be a LIST, got {type(lst).__name__}")
        if not lst:
            raise DSLValidationError("Cannot find max of empty list")
        if not all(isinstance(x, int) for x in lst):
            raise DSLValidationError("max requires a list of integers")
        return max(lst)

    def _evaluate_min(self, head, args):
        """Evaluate (min LIST) expression."""
        self._validate_arg_count(head, args, 1)
        lst = args[0]
        # Check if it's a preserved expression
        if self._is_preserved_expression(lst):
            return [head, lst]
        if not isinstance(lst, list):
            raise DSLValidationError(f"Argument 1 must be a LIST, got {type(lst).__name__}")
        if not lst:
            raise DSLValidationError("Cannot find min of empty list")
        if not all(isinstance(x, int) for x in lst):
            raise DSLValidationError("min requires a list of integers")
        return min(lst)

    def _evaluate_map(self, head, args):
        """Evaluate (map LIST FUNC) expression."""
        self._validate_arg_count(head, args, 2)
        lst, func = args

        # Check if list is a preserved expression (func is Lambda, not a list, so don't check it)
        if self._is_preserved_expression(lst):
            return [head, lst, func]
        if not isinstance(lst, list):
            raise DSLValidationError(f"Argument 1 must be a LIST, got {type(lst).__name__}")
        if not isinstance(func, Lambda):
            raise DSLValidationError(f"Argument 2 must be a Lambda, got {type(func).__name__}")

        # Apply function to each element
        result = []
        for item in lst:
            result.append(self._call_lambda(func, [item]))
        return result

    def _evaluate_reduce(self, head, args):
        """Evaluate (reduce LIST FUNC) expression."""
        self._validate_arg_count(head, args, 2)
        lst, func = args

        # Check if list is a preserved expression (func is Lambda, not a list, so don't check it)
        if self._is_preserved_expression(lst):
            return [head, lst, func]
        if not isinstance(lst, list):
            raise DSLValidationError(f"Argument 1 must be a LIST, got {type(lst).__name__}")
        if not isinstance(func, Lambda):
            raise DSLValidationError(f"Argument 2 must be a Lambda, got {type(func).__name__}")

        if not lst:
            raise DSLValidationError("Cannot reduce empty list")

        # Reduce: apply function cumulatively
        accumulator = lst[0]
        for item in lst[1:]:
            accumulator = self._call_lambda(func, [accumulator, item])
        return accumulator

    def _evaluate_max_by(self, head, args):
        """Evaluate (max_by LIST FUNC) expression."""
        self._validate_arg_count(head, args, 2)
        lst, func = args

        # Check if list is a preserved expression (func is Lambda, not a list, so don't check it)
        # Only preserve if it's actually a preserved expression (starts with function name string)
        if isinstance(lst, list) and self._is_preserved_expression(lst):
            return [head, lst, func]
        # Also preserve if list contains symbolic values
        if isinstance(lst, list):
            for item in lst:
                if isinstance(item, (SymbolicTeam, SymbolicMatch)):
                    return [head, lst, func]
        if not isinstance(lst, list):
            raise DSLValidationError(f"Argument 1 must be a LIST, got {type(lst).__name__}")
        if not isinstance(func, Lambda):
            raise DSLValidationError(f"Argument 2 must be a Lambda, got {type(func).__name__}")

        if not lst:
            raise DSLValidationError("Cannot find max_by of empty list")

        # Find element with maximum value according to function
        max_val = None
        max_elem = None
        for item in lst:
            val = self._call_lambda(func, [item])
            if not isinstance(val, int):
                raise DSLValidationError("max_by function must return an integer")
            if max_val is None or val > max_val:
                max_val = val
                max_elem = item
        return max_elem

    def _evaluate_min_by(self, head, args):
        """Evaluate (min_by LIST FUNC) expression."""
        self._validate_arg_count(head, args, 2)
        lst, func = args

        # Check if list is a preserved expression (func is Lambda, not a list, so don't check it)
        if self._is_preserved_expression(lst):
            return [head, lst, func]
        if not isinstance(lst, list):
            raise DSLValidationError(f"Argument 1 must be a LIST, got {type(lst).__name__}")
        if not isinstance(func, Lambda):
            raise DSLValidationError(f"Argument 2 must be a Lambda, got {type(func).__name__}")

        if not lst:
            raise DSLValidationError("Cannot find min_by of empty list")

        # Find element with minimum value according to function
        min_val = None
        min_elem = None
        for item in lst:
            val = self._call_lambda(func, [item])
            if not isinstance(val, int):
                raise DSLValidationError("min_by function must return an integer")
            if min_val is None or val < min_val:
                min_val = val
                min_elem = item
        return min_elem


def _collect_literals(text: str):
    """Pull out raw team and match literals for a quick reference-existence check.

    Returns (team_literals, match_literals) — lists of (raw_inside, position) tuples,
    skipping things that aren't directly resolvable (MatchName::winner, tag::Foo).
    """
    teams: list[tuple[str, int]] = []
    matches: list[tuple[str, int]] = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == "[":
            j = text.find("]", i + 1)
            if j == -1:
                break
            inner = text[i + 1 : j].strip()
            teams.append((inner, i))
            i = j + 1
            continue
        if c == "{":
            j = text.find("}", i + 1)
            if j == -1:
                break
            inner = text[i + 1 : j].strip()
            matches.append((inner, i))
            i = j + 1
            continue
        i += 1
    return teams, matches


def _check_references(text: str, event: str) -> list[str]:
    """Return a list of warnings about unresolvable team/match/tag references.

    A `[name]` literal must resolve to:
      - a team id, or
      - a `tag::TagName` for a Tag that exists in this event, or
      - `MatchName::winner` / `MatchName::loser` for a match that exists.
    A `{name}` literal must name a match in this event.
    Anything that doesn't match these rules gets a warning; symbolic references
    that legitimately can't be resolved yet (e.g. an unset tag's team) are not
    warned about here, only typoed names are.
    """
    warnings: list[str] = []
    teams, matches = _collect_literals(text)
    known_match_names: list[str] | None = None
    known_tag_names: list[str] | None = None
    for inner, pos in teams:
        if not inner:
            continue
        if "::" in inner:
            head, _, tail = inner.partition("::")
            if head == "tag":
                if not Tag.query.filter_by(name=tail, event=event).first():
                    if known_tag_names is None:
                        known_tag_names = [t.name for t in Tag.query.filter_by(event=event).all()]
                    suggestion = _suggest_function(tail, known_tag_names)
                    hint = f" Did you mean 'tag::{suggestion}'?" if suggestion else ""
                    warnings.append(f"Unknown tag '[tag::{tail}]' at {_format_position(text, pos)}.{hint}")
                continue
            if tail in ("winner", "loser"):
                if not MatchDB.query.filter_by(name=head, event=event).first():
                    if known_match_names is None:
                        known_match_names = [m.name for m in MatchDB.query.filter_by(event=event).all()]
                    suggestion = _suggest_function(head, known_match_names)
                    hint = f" Did you mean '{suggestion}::{tail}'?" if suggestion else ""
                    warnings.append(f"Unknown match '[{head}::{tail}]' at {_format_position(text, pos)}.{hint}")
                continue
            warnings.append(
                f"Invalid team literal '[{inner}]' at {_format_position(text, pos)} — "
                "expected a team id, tag::TagName, or MatchName::winner/loser."
            )
            continue
        if not TeamDB.query.filter_by(id=inner).first():
            all_names = [t.id for t in TeamDB.query.all()]
            suggestion = _suggest_function(inner, all_names)
            hint = f" Did you mean '{suggestion}'?" if suggestion else ""
            warnings.append(f"Unknown team '[{inner}]' at {_format_position(text, pos)}.{hint}")
    for inner, pos in matches:
        if not inner:
            continue
        if not MatchDB.query.filter_by(name=inner, event=event).first():
            if known_match_names is None:
                known_match_names = [m.name for m in MatchDB.query.filter_by(event=event).all()]
            suggestion = _suggest_function(inner, known_match_names)
            hint = f" Did you mean '{{{suggestion}}}'?" if suggestion else ""
            warnings.append(f"Unknown match '{{{inner}}}' at {_format_position(text, pos)}.{hint}")
    return warnings


def get_parser(event: str, match_resolver=None):
    """
    Create a parser for the given event (tournament URL).

    If match_resolver is provided, it is used to resolve match names when
    parsing (e.g. for skip_condition). It should be a callable(name) -> Match
    or SymbolicMatch. This avoids DB reads when matches are already in memory.
    """
    import os

    grammar_path = os.path.join(os.path.dirname(__file__), "grammar.lark")
    with open(grammar_path, "r") as g:
        parser = Lark(g, parser="lalr")

        parse_match = match_resolver if match_resolver is not None else (lambda x: parse_match_literal(x, event))

        def parse(text):
            # Cheap structural check first — gives clean position-aware errors before Lark tries.
            _check_balanced_brackets(text)
            try:
                tree = parser.parse(text)
            except UnexpectedInput as e:
                # Convert Lark's verbose dump to a one-line message with position.
                pos = getattr(e, "pos_in_stream", None)
                line = getattr(e, "line", None)
                col = getattr(e, "column", None)
                if line is not None and col is not None:
                    where = f"line {line}, col {col}"
                elif pos is not None:
                    where = _format_position(text, pos)
                else:
                    where = "an unknown position"
                got = ""
                tok = getattr(e, "token", None)
                if tok is not None and getattr(tok, "value", None):
                    got = f" near `{tok.value}`"
                raise DSLValidationError(f"Parse error at {where}{got}.") from e
            except LarkError as e:
                raise DSLValidationError(f"Parse error: {e}") from e
            interpreter = Simplifier(
                lambda x: parse_team_literal(x, event),
                parse_match,
            )
            return interpreter.visit(tree)

        def static_check(text):
            """Quick lint pass: balanced brackets and reference existence.

            Raises DSLValidationError on unbalanced brackets. Returns a list of
            soft warnings (typo-likely team/match names) without raising.
            """
            _check_balanced_brackets(text)
            return _check_references(text, event)

        class Parser:
            def __init__(self, parse_func, static_check_func):
                self.parse = parse_func
                self.static_check = static_check_func

        return Parser(parse, static_check)
