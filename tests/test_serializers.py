import pytest

from app.serializers.match_note_serializer import MatchNoteSerializer
from models import Match, MatchNote, Player, db


@pytest.mark.unit
def test_match_note_serializer_includes_team_id_for_team_targets(test_db, tournament):
    tournament_url = tournament.url
    p = Player(id="p1", name="Player One")
    m = Match(
        name="M1",
        event=tournament_url,
        schedule_type="DYNAMIC",
        status="NOT_STARTED",
        team1="team_1",
        team2="team_2",
    )
    db.session.add_all([p, m])
    db.session.flush()
    n = MatchNote(
        match=m.uuid,
        text="note",
        target="team1",
        created_by=p.id,
        player_id=p.id,
    )
    db.session.add(n)
    db.session.commit()

    # Re-load objects for serialization
    m_db = Match.query.filter_by(event=tournament_url, name="M1").first()
    n_db = MatchNote.query.filter_by(match=m_db.uuid).first()
    data = MatchNoteSerializer.to_dict(n_db, tournament_url, match=m_db)
    assert data["team_id"] == "team_1"
    assert data["player_id"] == "p1"
    assert data["text"] == "note"

