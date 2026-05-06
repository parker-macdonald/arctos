"""Tests for side competition models, services, and routes."""

import pytest
from sqlalchemy.exc import IntegrityError

from app.domain.enums import RegistrationStatus
from app.error_values import Err, Ok
from models import (
    Player,
    PlayerRegistration,
    SideComp,
    SideCompRegistration,
    TO,
    db,
)


def _make_player(player_id="p_alice", name="Alice"):
    p = Player(id=player_id, name=name, pw_hash="dummy_hash")
    p.set_password("testpass")
    db.session.add(p)
    db.session.commit()
    return p


def _confirm_event_registration(tournament_url, player_id, team_id=None):
    reg = PlayerRegistration(
        event=tournament_url,
        player=player_id,
        team=team_id,
        jersey_number="0",
        jersey_name="N/A",
        status=RegistrationStatus.CONFIRMED,
        paid=True,
    )
    db.session.add(reg)
    db.session.commit()
    return reg


def test_sidecomp_has_created_at(test_db, tournament):
    sc = SideComp(event=tournament.url, name="Dueling 1v1", type="DUELING")
    db.session.add(sc)
    db.session.commit()
    assert sc.created_at is not None


def test_sidecomp_registration_unique_per_player(test_db, tournament):
    p = _make_player()
    sc = SideComp(event=tournament.url, name="Chain", type="CHAIN_BREAKING")
    db.session.add(sc)
    db.session.flush()
    db.session.add(SideCompRegistration(comp=sc.id, player=p.id))
    db.session.commit()
    db.session.add(SideCompRegistration(comp=sc.id, player=p.id))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def _make_to(tournament_url, user_id, user_type="player"):
    db.session.add(TO(event=tournament_url, user_id=user_id, user_type=user_type))
    db.session.commit()


def test_sidecomp_service_create_to_succeeds(test_db, tournament):
    p = _make_player("to_user", "TO User")
    _make_to(tournament.url, p.id)

    from app.services.sidecomp_service import SideCompService

    res = SideCompService.create(
        tournament.url,
        actor_user_id=p.id,
        actor_user_type="player",
        name="Dueling 1v1",
        type="DUELING",
    )
    assert isinstance(res, Ok)
    sc = res.unwrap()
    assert sc.name == "Dueling 1v1"
    assert sc.type == "DUELING"
    assert sc.event == tournament.url


def test_sidecomp_service_create_non_to_forbidden(test_db, tournament):
    p = _make_player("not_to", "Non TO")

    from app.services.sidecomp_service import SideCompService

    res = SideCompService.create(
        tournament.url,
        actor_user_id=p.id,
        actor_user_type="player",
        name="X",
        type="DUELING",
    )
    assert isinstance(res, Err)
    assert res.unwrap_err().status_code == 403


def test_sidecomp_service_create_invalid_type(test_db, tournament):
    p = _make_player("to_user", "TO User")
    _make_to(tournament.url, p.id)

    from app.services.sidecomp_service import SideCompService

    res = SideCompService.create(
        tournament.url,
        actor_user_id=p.id,
        actor_user_type="player",
        name="X",
        type="NOT_A_REAL_TYPE",
    )
    assert isinstance(res, Err)
    assert res.unwrap_err().status_code == 400


def test_sidecomp_service_create_empty_name(test_db, tournament):
    p = _make_player("to_user", "TO User")
    _make_to(tournament.url, p.id)

    from app.services.sidecomp_service import SideCompService

    res = SideCompService.create(
        tournament.url,
        actor_user_id=p.id,
        actor_user_type="player",
        name="   ",
        type="DUELING",
    )
    assert isinstance(res, Err)
    assert res.unwrap_err().status_code == 400


def test_sidecomp_list_for_event_returns_all(test_db, tournament):
    sc1 = SideComp(event=tournament.url, name="A", type="DUELING")
    sc2 = SideComp(event=tournament.url, name="B", type="OTHER")
    db.session.add_all([sc1, sc2])
    db.session.commit()

    from app.services.sidecomp_service import SideCompService

    rows = SideCompService.list_for_event(tournament.url)
    names = sorted(r.name for r in rows)
    assert names == ["A", "B"]


def test_sidecomp_get_with_registrants(test_db, tournament):
    p = _make_player()
    sc = SideComp(event=tournament.url, name="C", type="CHAIN_BREAKING")
    db.session.add(sc)
    db.session.flush()
    db.session.add(SideCompRegistration(comp=sc.id, player=p.id))
    db.session.commit()

    from app.services.sidecomp_service import SideCompService

    res = SideCompService.get_with_registrants(sc.id)
    assert isinstance(res, Ok)
    comp, registrants = res.unwrap()
    assert comp.id == sc.id
    assert len(registrants) == 1
    reg, player = registrants[0]
    assert reg.player == p.id
    assert player.id == p.id


def test_sidecomp_get_with_registrants_not_found(test_db):
    from app.services.sidecomp_service import SideCompService

    res = SideCompService.get_with_registrants(99999)
    assert isinstance(res, Err)
    assert res.unwrap_err().status_code == 404
