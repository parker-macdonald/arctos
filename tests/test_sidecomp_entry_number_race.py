"""Tests for sidecomp entry_number collision retry."""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.error_values import Ok
from app.services.sidecomp_service import SideCompService
from models import (
    PlayerRegistration,
    SideComp,
    Tournament,
    Player,
    db,
)
from tests.utils import make_registrable_config


@pytest.fixture
def comp_setup(test_db):
    rc = make_registrable_config()
    t = Tournament(
        url="evt",
        name="Evt",
        registrable_config_id=rc.id,
        start_date=datetime.now(timezone.utc),
    )
    db.session.add(t)
    db.session.flush()
    sc = SideComp(event="evt", name="DT", type="DUELING", registration_open=True)
    db.session.add(sc)

    players = []
    for i in range(2):
        p = Player(id=f"p{i}", name=f"P{i}", pw_hash="x")
        p.set_password("pw")
        players.append(p)
        db.session.add(p)
        db.session.flush()
        db.session.add(PlayerRegistration(event="evt", player=p.id, status="CONFIRMED"))

    db.session.commit()
    return {"comp_id": sc.id, "players": players}


@pytest.mark.integration
def test_register_player_retries_on_entry_number_collision(comp_setup):
    """If _next_tournament_entry_number returns an already-taken value, the
    second registration retries internally and succeeds with a fresh number.

    This simulates the concurrent first-time assignment race that the
    uq_sidecomp_entry_numbers_tournament_entry_number constraint catches.
    """
    comp_id = comp_setup["comp_id"]
    p0, p1 = comp_setup["players"]

    res0 = SideCompService.register_player(comp_id, player_id=p0.id)
    assert isinstance(res0, Ok), repr(res0)

    # Force the candidate to collide with p0's number (1) once, then fall back
    # to the real computation (which yields a fresh 2) on retry.
    sequence = iter([1])
    real_next = SideCompService._next_tournament_entry_number

    def fake_next(tournament_url):
        try:
            return next(sequence)
        except StopIteration:
            return real_next(tournament_url)

    with patch.object(SideCompService, "_next_tournament_entry_number", side_effect=fake_next):
        res1 = SideCompService.register_player(comp_id, player_id=p1.id)
    assert isinstance(res1, Ok), repr(res1)

    assert SideCompService.entry_number_for("evt", p0.id) == 1
    assert SideCompService.entry_number_for("evt", p1.id) == 2
