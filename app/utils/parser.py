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
(skip-condition MATCH) -> BOOL

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

from lark import Lark, Transformer, v_args
from functools import lru_cache
from sqlalchemy import or_, and_
from app.models import Match as MatchDB, Point as PointDB, Team as TeamDB, db, Tag
from app.domain.enums import WinnerSide


class DSLValidationError(Exception):
    """Raised when DSL expression validation fails."""
    pass

def parse_team_literal(literal: str, event: str):
    """parse team literal into Team object or None if not found. parses tags and match winners/losers just like normal options for team references.

    Args:
        literal (str): literal inside of square brackets
        event (str): tournament url
    Returns:
        Team | None: team object or none
    """
    if '::' not in literal:
        return Team(TeamDB.query.filter_by(id=literal).first(), event)
    else:
        split = literal.split("::")
        assert len(split) == 2, f"Invalid team literal: {literal}"
        base, suffix = split
        if base == "winner":
            return Match(MatchDB.query.filter_by(name=suffix, event=event).first(), event).winner()
        elif base == "loser":
            return Match(MatchDB.query.filter_by(name=suffix, event=event).first(), event).loser()
        elif base == "tag":
            tag = Tag.query.filter_by(name=suffix, event=event).first()
            if tag and tag.team:
                return Team(TeamDB.query.filter_by(id=tag.team).first(), event)
            return None
        else:
            raise ValueError(f"Invalid team literal: {literal}")

def parse_match_literal(literal: str, event: str):
    obj = MatchDB.query.filter_by(name=literal, event=event).first()
    if obj is None:
        return None
    return Match(obj, event)


class Team:
    def __init__(self, obj: TeamDB, event: str):
        self.url = event
        self.obj = obj
    @lru_cache
    def points_won(self, m = None):
        # Filter Point columns first (before join) to reduce join set
        query = PointDB.query.filter(PointDB.rerolled == False)
        if m is not None:
            query = query.filter(PointDB.match == m.uuid)
        # Then join and filter on Match columns
        query = query.join(MatchDB, PointDB.match == MatchDB.uuid).filter(
            MatchDB.event == self.url,
            or_(
                and_(MatchDB.team1 == self.obj.id, PointDB.winner == WinnerSide.TEAM1),
                and_(MatchDB.team2 == self.obj.id, PointDB.winner == WinnerSide.TEAM2)
            )
        )
        return query.count()
    @lru_cache
    def points_lost(self, m = None):
        query = PointDB.query.filter(PointDB.rerolled == False)
        if m is not None:
            query = query.filter(PointDB.match == m.uuid)
        query = query.join(MatchDB, PointDB.match == MatchDB.uuid).filter(
            MatchDB.event == self.url,
            or_(
                and_(MatchDB.team1 == self.obj.id, PointDB.winner == WinnerSide.TEAM2),
                and_(MatchDB.team2 == self.obj.id, PointDB.winner == WinnerSide.TEAM1)
            )
        )
        return query.count()
    @lru_cache
    def wins(self):
        return MatchDB.query.filter_by(event=self.url, team1=self.obj.id, match_winner=WinnerSide.TEAM1).count() + MatchDB.query.filter_by(event=self.url, team2=self.obj.id, match_winner=WinnerSide.TEAM2).count()
    @lru_cache
    def losses(self):
        return MatchDB.query.filter_by(event=self.url, team1=self.obj.id, match_winner=WinnerSide.TEAM2).count() + MatchDB.query.filter_by(event=self.url, team2=self.obj.id, match_winner=WinnerSide.TEAM1).count()

    def __hash__(self):
        return hash((self.url, self.obj.id))


class Match:
    def __init__(self, obj: MatchDB, event: str):
        self.url = event
        self.obj = obj
    def winner(self):
        winner = self.obj.winner_team_id()
        if winner is None:
            return None 
        return Team(TeamDB.query.filter_by(id=winner).first(), self.url)
    def loser(self):
        loser = self.obj.loser_team_id()
        if loser is None:
            return None
        return Team(TeamDB.query.filter_by(id=loser).first(), self.url)
    def __hash__(self):
        return hash((self.url, self.obj.uuid))

from lark import Transformer, Token
from typing import Any, Optional

class Simplifier(Transformer):
    """Simplifies DSL expressions by evaluating what can be known at compile-time."""
    
    def __init__(self, parse_team_literal, parse_match_literal):
        super().__init__()
        self.parse_team_literal = parse_team_literal
        self.parse_match_literal = parse_match_literal
    
    def _validate_arg_count(self, head, args, expected_count, optional_count=0):
        """Validate argument count. Raises DSLValidationError if invalid."""
        min_count = expected_count - optional_count
        max_count = expected_count
        actual_count = len(args)
        if actual_count < min_count or actual_count > max_count:
            raise DSLValidationError(
                f"({head} ...) expects {expected_count} argument(s), got {actual_count}"
            )
    
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
                raise DSLValidationError(
                    f"Argument {arg_position} must be a TEAM, got {type(value).__name__}"
                )
        elif expected_type == "MATCH":
            if not isinstance(value, Match):
                raise DSLValidationError(
                    f"Argument {arg_position} must be a MATCH, got {type(value).__name__}"
                )
        elif expected_type == "INT":
            if not isinstance(value, int):
                raise DSLValidationError(
                    f"Argument {arg_position} must be an INT, got {type(value).__name__}"
                )
        elif expected_type == "BOOL":
            if not isinstance(value, bool):
                raise DSLValidationError(
                    f"Argument {arg_position} must be a BOOL, got {type(value).__name__}"
                )
        elif expected_type == "LIST":
            if not isinstance(value, list):
                raise DSLValidationError(
                    f"Argument {arg_position} must be a LIST, got {type(value).__name__}"
                )
        elif expected_type == "ANY":
            pass  # No validation needed
        
    # Atom transformations
    def int_atom(self, items):
        return int(items[0])
    
    def bool_atom(self, items):
        return items[0] == "true"
    
    def nil_atom(self, _):
        return None
    
    def team_atom(self, items):
        # items[0] is the full string including brackets
        team_str = str(items[0])[1:-1]  # Remove brackets
        return self.parse_team_literal(team_str)
    
    def match_atom(self, items):
        # items[0] is the full string including braces
        match_str = str(items[0])[1:-1]  # Remove braces
        return self.parse_match_literal(match_str)
    
    def identifier_atom(self, items):
        # Return as-is for variable names
        return str(items[0])
    
    # Main expression handling
    def list(self, items):
        """Process a list/s-expression."""
        if not items:
            return []  # Empty list
        
        head = items[0]
        args = items[1:]
        
        # Handle special forms
        if head == "if":
            return self._simplify_if(head, args)
        elif head == "lambda":
            # Lambda cannot be simplified further at this stage
            return [head] + args
        elif head == "cons":
            return self._simplify_cons(head, args)
        elif head == "car":
            return self._simplify_car(head, args)
        elif head == "cdr":
            return self._simplify_cdr(head, args)
        elif head == "get":
            return self._simplify_get(head, args)
        elif head == "or-default":
            return self._simplify_or_default(head, args)
        elif head == "len":
            return self._simplify_len(head, args)
        elif head == "map":
            # Cannot simplify map fully without executing the function
            return [head] + args
        elif head == "reduce":
            # Cannot simplify reduce fully without executing the function
            return [head] + args
        elif head == "max":
            return self._simplify_max(head, args)
        elif head == "min":
            return self._simplify_min(head, args)
        elif head == "max_by":
            # Cannot simplify without executing the function
            return [head] + args
        elif head == "min_by":
            # Cannot simplify without executing the function
            return [head] + args
        
        # Handle arithmetic and comparison operators
        if head in {"+", "-", "*", "/", ">", "<", ">=", "<=", "=="}:
            return self._simplify_binary_op(head, args)
        elif head in {"or", "and"}:
            return self._simplify_logical_op(head, args)
        
        # Handle team/match operations
        if head == "wins":
            return self._simplify_wins(head, args)
        elif head == "losses":
            return self._simplify_losses(head, args)
        elif head == "winner":
            return self._simplify_winner(head, args)
        elif head == "loser":
            return self._simplify_loser(head, args)
        elif head == "points-won":
            return self._simplify_points_won(head, args)
        elif head == "points-lost":
            return self._simplify_points_lost(head, args)
        elif head == "skip-condition":
            return self._simplify_skip_condition(head, args)
        
        # If we don't recognize it as a built-in, leave it as-is
        return [head] + args
    
    # Helper methods for simplification
    def _simplify_if(self, head, args):
        """Simplify if expression if condition can be evaluated."""
        self._validate_arg_count(head, args, 3)
        cond, if_true, if_false = args
        
        # If condition is a known boolean, we can simplify
        if isinstance(cond, bool):
            return if_true if cond else if_false
        
        # If both branches are the same value
        if if_true == if_false:
            return if_true
        
        return [head, cond, if_true, if_false]
    
    def _simplify_binary_op(self, op, args):
        """Simplify binary operations if both operands are known."""
        self._validate_arg_count(op, args, 2)
        a, b = args
        
        # Only simplify if both are integers (for arithmetic/comp) or comparable (for ==)
        if op in {"+", "-", "*", "/", ">", "<", ">=", "<="}:
            if not isinstance(a, int):
                raise DSLValidationError(
                    f"Argument 1 of ({op} ...) must be an INT, got {type(a).__name__}"
                )
            if not isinstance(b, int):
                raise DSLValidationError(
                    f"Argument 2 of ({op} ...) must be an INT, got {type(b).__name__}"
                )
            if isinstance(a, int) and isinstance(b, int):
                if op == "+": return a + b
                elif op == "-": return a - b
                elif op == "*": return a * b
                elif op == "/": return a // b if b != 0 else None  # Integer division
                elif op == ">": return a > b
                elif op == "<": return a < b
                elif op == ">=": return a >= b
                elif op == "<=": return a <= b
        elif op == "==":
            # == works on any comparable values
            if (isinstance(a, (int, bool, type(None))) and 
                isinstance(b, (int, bool, type(None)))):
                return a == b
            # For team/match objects, compare identity
            elif hasattr(a, '__hash__') and hasattr(b, '__hash__'):
                return a is b  # Compare object identity
        
        return [op, a, b]
    
    def _simplify_logical_op(self, op, args):
        """Simplify logical operations if possible."""
        self._validate_arg_count(op, args, 2)
        a, b = args
        # Type validation for logical ops is lenient - they can work with any values
        
        if isinstance(a, bool) and isinstance(b, bool):
            if op == "or": return a or b
            elif op == "and": return a and b
        
        # Short-circuit evaluation possibilities
        if op == "or":
            if a is True: return True
            if b is True: return True
            if a is False: return b
            if b is False: return a
        elif op == "and":
            if a is False: return False
            if b is False: return False
            if a is True: return b
            if b is True: return a
        
        return [op, a, b]
    
    def _simplify_wins(self, head, args):
        """Simplify (wins TEAM) expression."""
        self._validate_arg_count(head, args, 1)
        team = args[0]
        if not isinstance(team, Team):
            return [head, team]  # Can't simplify if team is not resolved
        return team.wins()
    
    def _simplify_losses(self, head, args):
        """Simplify (losses TEAM) expression."""
        self._validate_arg_count(head, args, 1)
        team = args[0]
        if not isinstance(team, Team):
            return [head, team]  # Can't simplify if team is not resolved
        return team.losses()
    
    def _simplify_winner(self, head, args):
        """Simplify (winner MATCH) expression."""
        self._validate_arg_count(head, args, 1)
        match = args[0]
        self._validate_type(match, "MATCH", "MATCH", 1)
        winner = match.winner()
        if winner is not None:
            return winner
        return [head, match]
    
    def _simplify_loser(self, head, args):
        """Simplify (loser MATCH) expression."""
        self._validate_arg_count(head, args, 1)
        match = args[0]
        if not isinstance(match, Match):
            return [head, match]  # Can't simplify if match is not resolved
        loser = match.loser()
        if loser is not None:
            return loser
        return [head, match]
    
    def _simplify_points_won(self, head, args):
        """Simplify (points-won TEAM MATCH?) expression."""
        if len(args) == 1:
            # (points-won TEAM)
            team = args[0]
            if not isinstance(team, Team):
                return [head, team]  # Can't simplify if team is not resolved
            return team.points_won()
        elif len(args) == 2:
            # (points-won TEAM MATCH)
            team, match = args
            if not isinstance(team, Team):
                return [head, team, match]  # Can't simplify if team is not resolved
            if not isinstance(match, Match):
                return [head, team, match]  # Can't simplify if match is not resolved
            return team.points_won(match)
        else:
            raise DSLValidationError(
                f"({head} ...) expects 1 or 2 arguments, got {len(args)}"
            )
    
    def _simplify_points_lost(self, head, args):
        """Simplify (points-lost TEAM MATCH?) expression."""
        if len(args) == 1:
            # (points-lost TEAM)
            team = args[0]
            if not isinstance(team, Team):
                return [head, team]  # Can't simplify if team is not resolved
            return team.points_lost()
        elif len(args) == 2:
            # (points-lost TEAM MATCH)
            team, match = args
            if not isinstance(team, Team):
                return [head, team, match]  # Can't simplify if team is not resolved
            if not isinstance(match, Match):
                return [head, team, match]  # Can't simplify if match is not resolved
            return team.points_lost(match)
        else:
            raise DSLValidationError(
                f"({head} ...) expects 1 or 2 arguments, got {len(args)}"
            )
    
    def _simplify_skip_condition(self, head, args):
        """Simplify (skip-condition MATCH) expression."""
        self._validate_arg_count(head, args, 1)
        match = args[0]
        if not isinstance(match, Match):
            return [head, match]  # Can't simplify if match is not resolved
        
        # Get the match's skip_condition
        skip_condition = match.obj.skip_condition if hasattr(match.obj, 'skip_condition') else None
        
        if not skip_condition or not skip_condition.strip():
            # No skip condition, return False (match should not be skipped)
            return False
        
        # Try to parse and simplify the skip_condition
        try:
            # Get parser for this event
            parser = get_parser(match.url)
            # Parse and simplify the skip_condition expression
            tree = parser.parse(skip_condition.strip())
            # tree is already simplified by the transformer
            
            # If it simplified to a boolean, return that
            if isinstance(tree, bool):
                return tree
            # If it simplified to None (NIL), treat as False
            if tree is None:
                return False
            # Otherwise, keep it as unsimplifiable
            return [head, match]
        except Exception:
            # If parsing fails, keep it as unsimplifiable
            return [head, match]
    
    def _simplify_cons(self, head, args):
        """Simplify (cons ...) expression."""
        # cons creates a list from arguments
        if all(arg is not None for arg in args):
            # If all args are known values, create a list
            return list(args)
        return [head] + args
    
    def _simplify_car(self, head, args):
        """Simplify (car LIST) expression."""
        self._validate_arg_count(head, args, 1)
        lst = args[0]
        self._validate_type(lst, "LIST", "LIST", 1)
        if lst:
            return lst[0]
        return [head, lst]
    
    def _simplify_cdr(self, head, args):
        """Simplify (cdr LIST) expression."""
        self._validate_arg_count(head, args, 1)
        lst = args[0]
        if not isinstance(lst, list):
            raise DSLValidationError(
                f"Argument 1 must be a LIST, got {type(lst).__name__}"
            )
        if lst:
            return lst[1:]
        return [head, lst]
    
    def _simplify_get(self, head, args):
        """Simplify (get INDEX LIST) expression."""
        self._validate_arg_count(head, args, 2)
        index, lst = args
        self._validate_type(index, "INT", "INT", 1)
        self._validate_type(lst, "LIST", "LIST", 2)
        if 0 <= index < len(lst):
            return lst[index]
        else:
            return None  # NIL for out-of-bounds
    
    def _simplify_or_default(self, head, args):
        """Simplify (or-default VAL DEFAULT) expression."""
        self._validate_arg_count(head, args, 2)
        val, default = args
        # No type validation - accepts any types
        if val is not None:  # NIL is represented as None
            return val
        return default
    
    def _simplify_len(self, head, args):
        """Simplify (len LIST) expression."""
        self._validate_arg_count(head, args, 1)
        lst = args[0]
        if not isinstance(lst, list):
            raise DSLValidationError(
                f"Argument 1 must be a LIST, got {type(lst).__name__}"
            )
        return len(lst)
    
    def _simplify_max(self, head, args):
        """Simplify (max LIST) expression."""
        self._validate_arg_count(head, args, 1)
        lst = args[0]
        if not isinstance(lst, list):
            raise DSLValidationError(
                f"Argument 1 must be a LIST, got {type(lst).__name__}"
            )
        if lst and all(isinstance(x, int) for x in lst):
            return max(lst)
        return [head, lst]
    
    def _simplify_min(self, head, args):
        """Simplify (min LIST) expression."""
        self._validate_arg_count(head, args, 1)
        lst = args[0]
        if not isinstance(lst, list):
            raise DSLValidationError(
                f"Argument 1 must be a LIST, got {type(lst).__name__}"
            )
        if lst and all(isinstance(x, int) for x in lst):
            return min(lst)
        return [head, lst]

def get_parser(event: str):
    import os
    grammar_path = os.path.join(os.path.dirname(__file__), 'grammar.lark')
    with open(grammar_path, 'r') as g:
        p = Lark(g, parser='lalr', transformer=Simplifier(lambda x: parse_team_literal(x, event), lambda x: parse_match_literal(x, event)))
    return p