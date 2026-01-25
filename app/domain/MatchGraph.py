from app.models.match import Match
from app.error_values import Some, Null, Option, Ok, Err, Result, allow_Q
from datetime import datetime
from app.domain.enums import ScheduleType

class MatchGraph:
    def __init__(self,
                 uuid: str,
                 team1: Option[MatchGraph],
                 team2: Option[MatchGraph],
                 refs: List[Option[MatchGraph]],
                 prev_match: Option[MatchGraph],
                 next_match: Option[MatchGraph],
                 nominal_start_time: datetime,
                 nominal_length: int,
                 confirmed_start_time: Option[datetime],
                 completed_time: Option[datetime],
                 kind: ScheduleType):
        self.name = name
        self.team1 = team1
        self.team2 = team2
        self.refs = refs
        self.prev_match = prev_match
        self.next_match = next_match
        self.kind = kind
    def deps(self):
        deps = []
        if self.team1

    
