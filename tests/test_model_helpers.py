import pytest

from models import Match


@pytest.mark.unit
def test_match_winner_loser_team_id_properties():
    m = Match(
        team1="a",
        team2="b",
        match_winner="TEAM1",
        status="COMPLETED",
        schedule_type="SAFE",
        name="x",
        event="e",
    )
    assert m.winner_team_id == "a"
    assert m.loser_team_id == "b"

    m2 = Match(
        team1="a",
        team2="b",
        match_winner="TEAM2",
        status="COMPLETED",
        schedule_type="SAFE",
        name="x2",
        event="e",
    )
    assert m2.winner_team_id == "b"
    assert m2.loser_team_id == "a"

    m3 = Match(
        team1="a",
        team2="b",
        match_winner=None,
        status="COMPLETED",
        schedule_type="SAFE",
        name="x3",
        event="e",
    )
    assert m3.winner_team_id is None
    assert m3.loser_team_id is None
