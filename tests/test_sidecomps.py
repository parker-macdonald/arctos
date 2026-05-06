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
    SideCompResult,
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


def test_sidecomp_update_changes_name_and_type(test_db, tournament):
    p = _make_player("to_user", "TO User")
    _make_to(tournament.url, p.id)
    sc = SideComp(event=tournament.url, name="Old", type="DUELING")
    db.session.add(sc)
    db.session.commit()

    from app.services.sidecomp_service import SideCompService

    res = SideCompService.update(
        sc.id,
        actor_user_id=p.id,
        actor_user_type="player",
        name="New",
        type="OTHER",
    )
    assert isinstance(res, Ok)
    db.session.refresh(sc)
    assert sc.name == "New"
    assert sc.type == "OTHER"


def test_sidecomp_update_partial(test_db, tournament):
    p = _make_player("to_user", "TO User")
    _make_to(tournament.url, p.id)
    sc = SideComp(event=tournament.url, name="Old", type="DUELING")
    db.session.add(sc)
    db.session.commit()

    from app.services.sidecomp_service import SideCompService

    res = SideCompService.update(
        sc.id,
        actor_user_id=p.id,
        actor_user_type="player",
        name="NewName",
    )
    assert isinstance(res, Ok)
    db.session.refresh(sc)
    assert sc.name == "NewName"
    assert sc.type == "DUELING"


def test_sidecomp_update_non_to_forbidden(test_db, tournament):
    p = _make_player("non_to", "Non TO")
    sc = SideComp(event=tournament.url, name="X", type="DUELING")
    db.session.add(sc)
    db.session.commit()

    from app.services.sidecomp_service import SideCompService

    res = SideCompService.update(
        sc.id,
        actor_user_id=p.id,
        actor_user_type="player",
        name="Y",
    )
    assert isinstance(res, Err)
    assert res.unwrap_err().status_code == 403


def test_sidecomp_delete_cascades(test_db, tournament):
    to_user = _make_player("to_user", "TO User")
    other = _make_player("other_player", "Other")
    _make_to(tournament.url, to_user.id)
    sc = SideComp(event=tournament.url, name="Z", type="DUELING")
    db.session.add(sc)
    db.session.flush()
    db.session.add(SideCompRegistration(comp=sc.id, player=other.id))
    db.session.add(SideCompResult(comp=sc.id, player=other.id))
    db.session.commit()
    comp_id = sc.id

    from app.services.sidecomp_service import SideCompService

    res = SideCompService.delete(
        comp_id, actor_user_id=to_user.id, actor_user_type="player"
    )
    assert isinstance(res, Ok)
    assert SideComp.query.get(comp_id) is None
    assert SideCompRegistration.query.filter_by(comp=comp_id).count() == 0
    assert SideCompResult.query.filter_by(comp=comp_id).count() == 0


def test_register_player_succeeds_when_event_registered(test_db, tournament):
    p = _make_player()
    _confirm_event_registration(tournament.url, p.id)
    sc = SideComp(event=tournament.url, name="A", type="DUELING")
    db.session.add(sc)
    db.session.commit()

    from app.services.sidecomp_service import SideCompService

    res = SideCompService.register_player(sc.id, player_id=p.id)
    assert isinstance(res, Ok)
    reg = res.unwrap()
    assert reg.comp == sc.id
    assert reg.player == p.id
    assert reg.registered_by_to is False


def test_register_player_no_event_registration(test_db, tournament):
    p = _make_player()
    sc = SideComp(event=tournament.url, name="A", type="DUELING")
    db.session.add(sc)
    db.session.commit()

    from app.services.sidecomp_service import SideCompService

    res = SideCompService.register_player(sc.id, player_id=p.id)
    assert isinstance(res, Err)
    assert res.unwrap_err().status_code == 400


def test_register_player_cancelled_event_registration(test_db, tournament):
    p = _make_player()
    reg = _confirm_event_registration(tournament.url, p.id)
    reg.status = RegistrationStatus.CANCELLED
    db.session.commit()
    sc = SideComp(event=tournament.url, name="A", type="DUELING")
    db.session.add(sc)
    db.session.commit()

    from app.services.sidecomp_service import SideCompService

    res = SideCompService.register_player(sc.id, player_id=p.id)
    assert isinstance(res, Err)
    assert res.unwrap_err().status_code == 400


def test_register_player_duplicate_rejected(test_db, tournament):
    p = _make_player()
    _confirm_event_registration(tournament.url, p.id)
    sc = SideComp(event=tournament.url, name="A", type="DUELING")
    db.session.add(sc)
    db.session.commit()

    from app.services.sidecomp_service import SideCompService

    SideCompService.register_player(sc.id, player_id=p.id)
    res2 = SideCompService.register_player(sc.id, player_id=p.id)
    assert isinstance(res2, Err)
    assert res2.unwrap_err().status_code == 400


def test_register_player_unaffiliated_succeeds(test_db, tournament):
    """Players with no team_id on their event registration can still register."""
    p = _make_player()
    _confirm_event_registration(tournament.url, p.id, team_id=None)
    sc = SideComp(event=tournament.url, name="A", type="DUELING")
    db.session.add(sc)
    db.session.commit()

    from app.services.sidecomp_service import SideCompService

    res = SideCompService.register_player(sc.id, player_id=p.id)
    assert isinstance(res, Ok)


def test_deregister_player_removes_row(test_db, tournament):
    p = _make_player()
    _confirm_event_registration(tournament.url, p.id)
    sc = SideComp(event=tournament.url, name="A", type="DUELING")
    db.session.add(sc)
    db.session.flush()
    db.session.add(SideCompRegistration(comp=sc.id, player=p.id))
    db.session.commit()

    from app.services.sidecomp_service import SideCompService

    res = SideCompService.deregister_player(sc.id, player_id=p.id)
    assert isinstance(res, Ok)
    assert SideCompRegistration.query.filter_by(comp=sc.id, player=p.id).first() is None


def test_deregister_player_idempotent_when_missing(test_db, tournament):
    p = _make_player()
    sc = SideComp(event=tournament.url, name="A", type="DUELING")
    db.session.add(sc)
    db.session.commit()

    from app.services.sidecomp_service import SideCompService

    res = SideCompService.deregister_player(sc.id, player_id=p.id)
    assert isinstance(res, Ok)
