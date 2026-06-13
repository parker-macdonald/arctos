"""Tests for side competition models, services, and routes."""

import pytest
from sqlalchemy.exc import IntegrityError

from app.domain.enums import RegistrationStatus
from app.error_values import Err, Ok
from models import (
    Player,
    PlayerRegistration,
    SideComp,
    SideCompCategory,
    SideCompEntryNumber,
    SideCompRegistration,
    SideCompResult,
    TO,
    Tournament,
    db,
)
from tests.utils import login_as


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


def _make_league_sidecomp_context(registration_open=False):
    from datetime import datetime, timedelta, timezone

    from app.domain.enums import TeamRegistrationStatus
    from models import League, Team, TeamRegistration, Tournament
    from tests.utils import make_registrable_config

    cfg = make_registrable_config(team_registration_open=True, player_registration_open=True)
    league = League(url="lg", name="LG", registrable_config_id=cfg.id)
    db.session.add(league)
    db.session.flush()

    tournament = Tournament(
        url="lg-evt",
        name="League Event",
        start_date=datetime.now(timezone.utc),
        end_date=datetime.now(timezone.utc) + timedelta(days=1),
        league_id=league.url,
    )
    db.session.add(tournament)
    db.session.flush()

    to_user = _make_player("lg_to", "LG TO")
    db.session.add(TO(user_id=to_user.id, user_type="player", event=None, league_id=league.url))

    team = Team(id="lg_team", name="LG Team", pw_hash="dummy_hash")
    db.session.add(team)
    db.session.flush()
    db.session.add(
        TeamRegistration(
            event=None,
            league_id=league.url,
            team=team.id,
            pseudonym="LG Pseudonym",
            status=TeamRegistrationStatus.CONFIRMED,
        )
    )

    player = _make_player("lg_p1", "LG P1")
    db.session.add(
        PlayerRegistration(
            event=None,
            league_id=league.url,
            player=player.id,
            team=team.id,
            jersey_number="7",
            jersey_name="P1",
            status=RegistrationStatus.CONFIRMED,
            paid=True,
        )
    )

    sidecomp = SideComp(event=tournament.url, name="LG SC", type="DUELING", registration_open=registration_open)
    db.session.add(sidecomp)
    db.session.commit()

    return {
        "tournament": tournament,
        "to_user": to_user,
        "player": player,
        "sidecomp": sidecomp,
    }


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
    cat = SideCompCategory(comp=sc.id, name="Open")
    db.session.add(cat)
    db.session.flush()
    db.session.add(SideCompRegistration(comp=sc.id, player=other.id, category=cat.id))
    db.session.add(SideCompResult(comp=sc.id, player=other.id))
    db.session.commit()
    comp_id = sc.id

    from app.services.sidecomp_service import SideCompService

    res = SideCompService.delete(comp_id, actor_user_id=to_user.id, actor_user_type="player")
    assert isinstance(res, Ok)
    assert SideComp.query.get(comp_id) is None
    assert SideCompRegistration.query.filter_by(comp=comp_id).count() == 0
    assert SideCompResult.query.filter_by(comp=comp_id).count() == 0
    assert SideCompCategory.query.filter_by(comp=comp_id).count() == 0


def test_register_player_succeeds_when_event_registered(test_db, tournament):
    p = _make_player()
    _confirm_event_registration(tournament.url, p.id)
    sc = SideComp(event=tournament.url, name="A", type="DUELING", registration_open=True)
    db.session.add(sc)
    db.session.commit()

    from app.services.sidecomp_service import SideCompService

    res = SideCompService.register_player(sc.id, player_id=p.id)
    assert isinstance(res, Ok)
    reg = res.unwrap()
    assert reg.comp == sc.id
    assert reg.player == p.id
    assert reg.registered_by_to is False


def test_register_player_succeeds_with_league_scoped_registration(test_db):
    ctx = _make_league_sidecomp_context(registration_open=True)

    from app.services.sidecomp_service import SideCompService

    res = SideCompService.register_player(ctx["sidecomp"].id, player_id=ctx["player"].id)

    assert isinstance(res, Ok)
    reg = res.unwrap()
    assert reg.comp == ctx["sidecomp"].id
    assert reg.player == ctx["player"].id
    assert reg.registered_by_to is False


def test_register_player_no_event_registration(test_db, tournament):
    p = _make_player()
    sc = SideComp(event=tournament.url, name="A", type="DUELING", registration_open=True)
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
    sc = SideComp(event=tournament.url, name="A", type="DUELING", registration_open=True)
    db.session.add(sc)
    db.session.commit()

    from app.services.sidecomp_service import SideCompService

    res = SideCompService.register_player(sc.id, player_id=p.id)
    assert isinstance(res, Err)
    assert res.unwrap_err().status_code == 400


def test_register_player_duplicate_rejected(test_db, tournament):
    p = _make_player()
    _confirm_event_registration(tournament.url, p.id)
    sc = SideComp(event=tournament.url, name="A", type="DUELING", registration_open=True)
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
    sc = SideComp(event=tournament.url, name="A", type="DUELING", registration_open=True)
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


def test_register_player_as_to_succeeds(test_db, tournament):
    to_user = _make_player("to_user", "TO User")
    other = _make_player("p_other", "Other")
    _make_to(tournament.url, to_user.id)
    _confirm_event_registration(tournament.url, other.id)
    sc = SideComp(event=tournament.url, name="A", type="DUELING")
    db.session.add(sc)
    db.session.commit()

    from app.services.sidecomp_service import SideCompService

    res = SideCompService.register_player_as_to(
        sc.id,
        actor_user_id=to_user.id,
        actor_user_type="player",
        player_id=other.id,
    )
    assert isinstance(res, Ok)
    reg = res.unwrap()
    assert reg.registered_by_to is True


def test_register_player_as_to_succeeds_with_league_scoped_registration(test_db):
    ctx = _make_league_sidecomp_context()

    from app.services.sidecomp_service import SideCompService

    res = SideCompService.register_player_as_to(
        ctx["sidecomp"].id,
        actor_user_id=ctx["to_user"].id,
        actor_user_type="player",
        player_id=ctx["player"].id,
    )

    assert isinstance(res, Ok)
    reg = res.unwrap()
    assert reg.comp == ctx["sidecomp"].id
    assert reg.player == ctx["player"].id
    assert reg.registered_by_to is True


def test_register_player_as_to_non_to_forbidden(test_db, tournament):
    actor = _make_player("not_to", "Not TO")
    target = _make_player("p_other", "Other")
    _confirm_event_registration(tournament.url, target.id)
    sc = SideComp(event=tournament.url, name="A", type="DUELING")
    db.session.add(sc)
    db.session.commit()

    from app.services.sidecomp_service import SideCompService

    res = SideCompService.register_player_as_to(
        sc.id,
        actor_user_id=actor.id,
        actor_user_type="player",
        player_id=target.id,
    )
    assert isinstance(res, Err)
    assert res.unwrap_err().status_code == 403


def test_register_player_as_to_target_not_event_registered(test_db, tournament):
    to_user = _make_player("to_user", "TO User")
    target = _make_player("p_other", "Other")
    _make_to(tournament.url, to_user.id)
    sc = SideComp(event=tournament.url, name="A", type="DUELING")
    db.session.add(sc)
    db.session.commit()

    from app.services.sidecomp_service import SideCompService

    res = SideCompService.register_player_as_to(
        sc.id,
        actor_user_id=to_user.id,
        actor_user_type="player",
        player_id=target.id,
    )
    assert isinstance(res, Err)
    assert res.unwrap_err().status_code == 400


def test_deregister_player_as_to_idempotent(test_db, tournament):
    to_user = _make_player("to_user", "TO User")
    target = _make_player("p_other", "Other")
    _make_to(tournament.url, to_user.id)
    sc = SideComp(event=tournament.url, name="A", type="DUELING")
    db.session.add(sc)
    db.session.commit()

    from app.services.sidecomp_service import SideCompService

    res = SideCompService.deregister_player_as_to(
        sc.id,
        actor_user_id=to_user.id,
        actor_user_type="player",
        player_id=target.id,
    )
    assert isinstance(res, Ok)


def test_register_player_rejected_when_closed(test_db, tournament):
    """Self-registration is blocked when the comp is not open, even with event reg."""
    p = _make_player()
    _confirm_event_registration(tournament.url, p.id)
    sc = SideComp(event=tournament.url, name="A", type="DUELING")
    db.session.add(sc)
    db.session.commit()

    from app.services.sidecomp_service import SideCompService

    res = SideCompService.register_player(sc.id, player_id=p.id)
    assert isinstance(res, Err)
    assert res.unwrap_err().status_code == 400


def test_register_player_succeeds_when_opened(test_db, tournament):
    """Opening a closed comp via update unblocks player self-registration."""
    to_user = _make_player("to_user", "TO User")
    p = _make_player("p_alice2", "Alice2")
    _make_to(tournament.url, to_user.id)
    _confirm_event_registration(tournament.url, p.id)
    sc = SideComp(event=tournament.url, name="A", type="DUELING")
    db.session.add(sc)
    db.session.commit()

    from app.services.sidecomp_service import SideCompService

    closed = SideCompService.register_player(sc.id, player_id=p.id)
    assert isinstance(closed, Err)

    upd = SideCompService.update(
        sc.id,
        actor_user_id=to_user.id,
        actor_user_type="player",
        registration_open=True,
    )
    assert isinstance(upd, Ok)

    res = SideCompService.register_player(sc.id, player_id=p.id)
    assert isinstance(res, Ok)


def test_register_player_as_to_works_when_closed(test_db, tournament):
    """TO-driven registration must work regardless of registration_open state."""
    to_user = _make_player("to_user", "TO User")
    target = _make_player("p_other", "Other")
    _make_to(tournament.url, to_user.id)
    _confirm_event_registration(tournament.url, target.id)
    sc = SideComp(event=tournament.url, name="A", type="DUELING")
    db.session.add(sc)
    db.session.commit()
    assert sc.registration_open is False

    from app.services.sidecomp_service import SideCompService

    res = SideCompService.register_player_as_to(
        sc.id,
        actor_user_id=to_user.id,
        actor_user_type="player",
        player_id=target.id,
    )
    assert isinstance(res, Ok)


def test_register_player_assigns_entry_number_one(test_db, tournament):
    p = _make_player()
    _confirm_event_registration(tournament.url, p.id)
    sc = SideComp(event=tournament.url, name="A", type="DUELING", registration_open=True)
    db.session.add(sc)
    db.session.commit()

    from app.services.sidecomp_service import SideCompService

    res = SideCompService.register_player(sc.id, player_id=p.id)
    assert isinstance(res, Ok)
    assert SideCompService.entry_number_for(tournament.url, p.id) == 1


def test_register_player_assigns_sequential_entry_numbers(test_db, tournament):
    p1 = _make_player("p1", "P1")
    p2 = _make_player("p2", "P2")
    _confirm_event_registration(tournament.url, p1.id)
    _confirm_event_registration(tournament.url, p2.id)
    sc = SideComp(event=tournament.url, name="A", type="DUELING", registration_open=True)
    db.session.add(sc)
    db.session.commit()

    from app.services.sidecomp_service import SideCompService

    SideCompService.register_player(sc.id, player_id=p1.id).unwrap()
    SideCompService.register_player(sc.id, player_id=p2.id).unwrap()
    assert SideCompService.entry_number_for(tournament.url, p1.id) == 1
    assert SideCompService.entry_number_for(tournament.url, p2.id) == 2


def test_entry_numbers_do_not_reuse_after_deregister(test_db, tournament):
    p1 = _make_player("p1", "P1")
    p2 = _make_player("p2", "P2")
    p3 = _make_player("p3", "P3")
    _confirm_event_registration(tournament.url, p1.id)
    _confirm_event_registration(tournament.url, p2.id)
    _confirm_event_registration(tournament.url, p3.id)
    sc = SideComp(event=tournament.url, name="A", type="DUELING", registration_open=True)
    db.session.add(sc)
    db.session.commit()

    from app.services.sidecomp_service import SideCompService

    SideCompService.register_player(sc.id, player_id=p1.id).unwrap()
    SideCompService.register_player(sc.id, player_id=p2.id).unwrap()
    assert SideCompService.entry_number_for(tournament.url, p1.id) == 1
    assert SideCompService.entry_number_for(tournament.url, p2.id) == 2

    SideCompService.deregister_player(sc.id, player_id=p1.id)

    SideCompService.register_player(sc.id, player_id=p3.id).unwrap()
    assert SideCompService.entry_number_for(tournament.url, p3.id) == 3


def test_entry_number_consistent_across_comps(test_db, tournament):
    """A player carries the same entry number across every side competition
    they enter within a tournament."""
    p1 = _make_player("p1", "P1")
    p2 = _make_player("p2", "P2")
    _confirm_event_registration(tournament.url, p1.id)
    _confirm_event_registration(tournament.url, p2.id)
    sc1 = SideComp(event=tournament.url, name="A", type="DUELING", registration_open=True)
    sc2 = SideComp(event=tournament.url, name="B", type="OTHER", registration_open=True)
    db.session.add_all([sc1, sc2])
    db.session.commit()

    from app.services.sidecomp_service import SideCompService

    # p1 enters sc1 first (number 1), then p2 enters sc1 (number 2).
    SideCompService.register_player(sc1.id, player_id=p1.id).unwrap()
    SideCompService.register_player(sc1.id, player_id=p2.id).unwrap()
    # Both join sc2 in the opposite order; their numbers must not change.
    SideCompService.register_player(sc2.id, player_id=p2.id).unwrap()
    SideCompService.register_player(sc2.id, player_id=p1.id).unwrap()

    assert SideCompService.entry_number_for(tournament.url, p1.id) == 1
    assert SideCompService.entry_number_for(tournament.url, p2.id) == 2


def test_entry_numbers_scoped_per_tournament(test_db, tournament):
    """Entry numbering restarts in a different tournament."""
    from datetime import datetime, timezone

    from tests.utils import make_registrable_config

    rc = make_registrable_config()
    other = Tournament(
        url="other-evt",
        name="Other",
        registrable_config_id=rc.id,
        start_date=datetime.now(timezone.utc),
    )
    db.session.add(other)
    db.session.commit()

    p = _make_player()
    _confirm_event_registration(tournament.url, p.id)
    _confirm_event_registration(other.url, p.id)
    sc_a = SideComp(event=tournament.url, name="A", type="DUELING", registration_open=True)
    sc_b = SideComp(event=other.url, name="B", type="DUELING", registration_open=True)
    db.session.add_all([sc_a, sc_b])
    db.session.commit()

    from app.services.sidecomp_service import SideCompService

    SideCompService.register_player(sc_a.id, player_id=p.id).unwrap()
    SideCompService.register_player(sc_b.id, player_id=p.id).unwrap()

    assert SideCompService.entry_number_for(tournament.url, p.id) == 1
    assert SideCompService.entry_number_for(other.url, p.id) == 1


def test_register_player_as_to_assigns_entry_number(test_db, tournament):
    to_user = _make_player("to_user", "TO User")
    target = _make_player("p_other", "Other")
    _make_to(tournament.url, to_user.id)
    _confirm_event_registration(tournament.url, target.id)
    sc = SideComp(event=tournament.url, name="A", type="DUELING")
    db.session.add(sc)
    db.session.commit()

    from app.services.sidecomp_service import SideCompService

    res = SideCompService.register_player_as_to(
        sc.id,
        actor_user_id=to_user.id,
        actor_user_type="player",
        player_id=target.id,
    )
    assert isinstance(res, Ok)
    assert SideCompService.entry_number_for(tournament.url, target.id) == 1


def test_entry_number_unique_per_tournament_player(test_db, tournament):
    p = _make_player()
    db.session.add(SideCompEntryNumber(tournament_url=tournament.url, player=p.id, entry_number=1))
    db.session.commit()
    db.session.add(SideCompEntryNumber(tournament_url=tournament.url, player=p.id, entry_number=2))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_entry_number_unique_per_tournament(test_db, tournament):
    p1 = _make_player("p1", "P1")
    p2 = _make_player("p2", "P2")
    db.session.add(SideCompEntryNumber(tournament_url=tournament.url, player=p1.id, entry_number=1))
    db.session.commit()
    db.session.add(SideCompEntryNumber(tournament_url=tournament.url, player=p2.id, entry_number=1))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_create_with_description(test_db, tournament):
    p = _make_player("to_user", "TO User")
    _make_to(tournament.url, p.id)

    from app.services.sidecomp_service import SideCompService

    res = SideCompService.create(
        tournament.url,
        actor_user_id=p.id,
        actor_user_type="player",
        name="Dueling 1v1",
        type="DUELING",
        description="Best of 3 sets, single elimination.",
    )
    assert isinstance(res, Ok)
    sc = res.unwrap()
    assert sc.description == "Best of 3 sets, single elimination."


def test_update_description_can_clear(test_db, tournament):
    p = _make_player("to_user", "TO User")
    _make_to(tournament.url, p.id)
    sc = SideComp(
        event=tournament.url,
        name="A",
        type="DUELING",
        description="initial",
    )
    db.session.add(sc)
    db.session.commit()

    from app.services.sidecomp_service import SideCompService

    res = SideCompService.update(
        sc.id,
        actor_user_id=p.id,
        actor_user_type="player",
        description="   ",
    )
    assert isinstance(res, Ok)
    db.session.refresh(sc)
    assert sc.description is None


def test_update_registration_open_toggle(test_db, tournament):
    p = _make_player("to_user", "TO User")
    _make_to(tournament.url, p.id)
    sc = SideComp(event=tournament.url, name="A", type="DUELING")
    db.session.add(sc)
    db.session.commit()
    assert sc.registration_open is False

    from app.services.sidecomp_service import SideCompService

    res = SideCompService.update(
        sc.id,
        actor_user_id=p.id,
        actor_user_type="player",
        registration_open=True,
    )
    assert isinstance(res, Ok)
    db.session.refresh(sc)
    assert sc.registration_open is True

    res = SideCompService.update(
        sc.id,
        actor_user_id=p.id,
        actor_user_type="player",
        registration_open=False,
    )
    assert isinstance(res, Ok)
    db.session.refresh(sc)
    assert sc.registration_open is False


def test_cancel_player_registrations_in_event_removes_only_matching(test_db, tournament):
    p1 = _make_player("p1", "P1")
    p2 = _make_player("p2", "P2")
    sc1 = SideComp(event=tournament.url, name="A", type="DUELING")
    sc2 = SideComp(event=tournament.url, name="B", type="OTHER")
    db.session.add_all([sc1, sc2])
    db.session.flush()
    db.session.add(SideCompRegistration(comp=sc1.id, player=p1.id))
    db.session.add(SideCompRegistration(comp=sc2.id, player=p1.id))
    db.session.add(SideCompRegistration(comp=sc1.id, player=p2.id))
    db.session.commit()

    from app.services.sidecomp_service import SideCompService

    SideCompService.cancel_player_registrations_in_event(tournament.url, p1.id)

    assert SideCompRegistration.query.filter_by(player=p1.id).count() == 0
    assert SideCompRegistration.query.filter_by(player=p2.id).count() == 1


def test_player_self_deregister_from_event_cascades(app, client, tournament):
    """Player self-deregister via /deregister-player should cascade to side comps."""
    from tests.utils import login_as

    with app.app_context():
        p = _make_player()
        _confirm_event_registration(tournament.url, p.id)
        sc = SideComp(event=tournament.url, name="A", type="DUELING")
        db.session.add(sc)
        db.session.flush()
        db.session.add(SideCompRegistration(comp=sc.id, player=p.id))
        db.session.commit()
        login_as(client, p)

    resp = client.post(f"/_api/{tournament.url}/deregister-player")
    assert resp.status_code == 200

    with app.app_context():
        assert SideCompRegistration.query.filter_by(player=p.id).count() == 0


def test_route_list_for_event_public(client, tournament):
    sc = SideComp(event=tournament.url, name="A", type="DUELING")
    db.session.add(sc)
    db.session.commit()

    resp = client.get(f"/_api/{tournament.url}/sidecomps")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert any(row["name"] == "A" and row["type"] == "DUELING" for row in payload)


def test_route_detail_public_with_registrants(client, tournament):
    p = _make_player()
    sc = SideComp(event=tournament.url, name="A", type="DUELING")
    db.session.add(sc)
    db.session.flush()
    db.session.add(SideCompRegistration(comp=sc.id, player=p.id))
    db.session.commit()

    resp = client.get(f"/_api/sidecomps/{sc.id}")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["name"] == "A"
    assert payload["type"] == "DUELING"
    assert len(payload["registrants"]) == 1
    assert payload["registrants"][0]["player_id"] == p.id


def test_route_detail_includes_entry_numbers(app, client, tournament):
    with app.app_context():
        p1 = _make_player("p1", "P1")
        p2 = _make_player("p2", "P2")
        _confirm_event_registration(tournament.url, p1.id)
        _confirm_event_registration(tournament.url, p2.id)
        sc = SideComp(event=tournament.url, name="A", type="DUELING", registration_open=True)
        db.session.add(sc)
        db.session.commit()
        comp_id = sc.id

        from app.services.sidecomp_service import SideCompService

        SideCompService.register_player(comp_id, player_id=p1.id)
        SideCompService.register_player(comp_id, player_id=p2.id)

    resp = client.get(f"/_api/sidecomps/{comp_id}")
    assert resp.status_code == 200
    payload = resp.get_json()
    entry_numbers = [r["entry_number"] for r in payload["registrants"]]
    assert entry_numbers == [1, 2]


def test_route_detail_not_found(client):
    resp = client.get("/_api/sidecomps/99999")
    assert resp.status_code == 404


def test_route_detail_viewer_flags_anonymous(client, tournament):
    sc = SideComp(event=tournament.url, name="A", type="DUELING")
    db.session.add(sc)
    db.session.commit()

    resp = client.get(f"/_api/sidecomps/{sc.id}")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["viewer_is_to"] is False
    assert payload["viewer_can_register"] is False
    assert payload["viewer_is_registered_in_comp"] is False


def test_route_detail_viewer_flags_event_player(app, client, tournament):
    with app.app_context():
        p = _make_player()
        _confirm_event_registration(tournament.url, p.id)
        sc = SideComp(event=tournament.url, name="A", type="DUELING", registration_open=True)
        db.session.add(sc)
        db.session.commit()
        comp_id = sc.id
        login_as(client, p)

    resp = client.get(f"/_api/sidecomps/{comp_id}")
    payload = resp.get_json()
    assert payload["viewer_is_to"] is False
    assert payload["viewer_can_register"] is True
    assert payload["viewer_is_registered_in_comp"] is False


def test_route_detail_viewer_flags_already_registered(app, client, tournament):
    with app.app_context():
        p = _make_player()
        _confirm_event_registration(tournament.url, p.id)
        sc = SideComp(event=tournament.url, name="A", type="DUELING")
        db.session.add(sc)
        db.session.flush()
        db.session.add(SideCompRegistration(comp=sc.id, player=p.id))
        db.session.commit()
        comp_id = sc.id
        login_as(client, p)

    resp = client.get(f"/_api/sidecomps/{comp_id}")
    payload = resp.get_json()
    assert payload["viewer_can_register"] is False
    assert payload["viewer_is_registered_in_comp"] is True


def test_route_detail_viewer_can_register_with_league_scoped_registration(app, client, test_db):
    with app.app_context():
        ctx = _make_league_sidecomp_context(registration_open=True)
        comp_id = ctx["sidecomp"].id
        login_as(client, ctx["player"])

    resp = client.get(f"/_api/sidecomps/{comp_id}")

    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["viewer_can_register"] is True
    assert payload["viewer_is_registered_in_comp"] is False


def test_route_detail_viewer_flags_to(app, client, tournament):
    with app.app_context():
        to_user = _make_player("to_user", "TO User")
        _make_to(tournament.url, to_user.id)
        sc = SideComp(event=tournament.url, name="A", type="DUELING")
        db.session.add(sc)
        db.session.commit()
        comp_id = sc.id
        login_as(client, to_user)

    resp = client.get(f"/_api/sidecomps/{comp_id}")
    payload = resp.get_json()
    assert payload["viewer_is_to"] is True


def test_route_create_to_succeeds(app, client, tournament):
    with app.app_context():
        to_user = _make_player("to_user", "TO User")
        _make_to(tournament.url, to_user.id)
        login_as(client, to_user)

    resp = client.post(
        f"/_api/{tournament.url}/sidecomps",
        json={"name": "Dueling", "type": "DUELING"},
    )
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["name"] == "Dueling"
    assert payload["type"] == "DUELING"


def test_route_create_non_to_forbidden(app, client, tournament):
    with app.app_context():
        p = _make_player("non_to", "Non TO")
        login_as(client, p)

    resp = client.post(
        f"/_api/{tournament.url}/sidecomps",
        json={"name": "X", "type": "DUELING"},
    )
    assert resp.status_code == 403


def test_route_update_to_succeeds(app, client, tournament):
    with app.app_context():
        to_user = _make_player("to_user", "TO User")
        _make_to(tournament.url, to_user.id)
        sc = SideComp(event=tournament.url, name="Old", type="DUELING")
        db.session.add(sc)
        db.session.commit()
        comp_id = sc.id
        login_as(client, to_user)

    resp = client.patch(
        f"/_api/sidecomps/{comp_id}",
        json={"name": "New"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["name"] == "New"


def test_route_create_with_description(app, client, tournament):
    with app.app_context():
        to_user = _make_player("to_user", "TO User")
        _make_to(tournament.url, to_user.id)
        login_as(client, to_user)

    resp = client.post(
        f"/_api/{tournament.url}/sidecomps",
        json={"name": "Dueling", "type": "DUELING", "description": "Single elim"},
    )
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["description"] == "Single elim"
    assert payload["registration_open"] is False


def test_route_update_open_close(app, client, tournament):
    with app.app_context():
        to_user = _make_player("to_user", "TO User")
        _make_to(tournament.url, to_user.id)
        sc = SideComp(event=tournament.url, name="A", type="DUELING")
        db.session.add(sc)
        db.session.commit()
        comp_id = sc.id
        login_as(client, to_user)

    resp = client.patch(
        f"/_api/sidecomps/{comp_id}",
        json={"registration_open": True},
    )
    assert resp.status_code == 200
    assert resp.get_json()["registration_open"] is True

    resp = client.get(f"/_api/sidecomps/{comp_id}")
    assert resp.status_code == 200
    assert resp.get_json()["registration_open"] is True


def test_route_detail_viewer_cannot_register_when_closed(app, client, tournament):
    with app.app_context():
        p = _make_player()
        _confirm_event_registration(tournament.url, p.id)
        sc = SideComp(event=tournament.url, name="A", type="DUELING")
        db.session.add(sc)
        db.session.commit()
        comp_id = sc.id
        login_as(client, p)

    resp = client.get(f"/_api/sidecomps/{comp_id}")
    payload = resp.get_json()
    assert payload["registration_open"] is False
    assert payload["viewer_can_register"] is False


def test_route_list_includes_registration_open(client, tournament):
    sc = SideComp(event=tournament.url, name="A", type="DUELING")
    db.session.add(sc)
    db.session.commit()

    resp = client.get(f"/_api/{tournament.url}/sidecomps")
    assert resp.status_code == 200
    rows = resp.get_json()
    row = next(r for r in rows if r["name"] == "A")
    assert "registration_open" in row
    assert row["registration_open"] is False


def test_route_delete_to_succeeds(app, client, tournament):
    with app.app_context():
        to_user = _make_player("to_user", "TO User")
        _make_to(tournament.url, to_user.id)
        sc = SideComp(event=tournament.url, name="Old", type="DUELING")
        db.session.add(sc)
        db.session.commit()
        comp_id = sc.id
        login_as(client, to_user)

    resp = client.delete(f"/_api/sidecomps/{comp_id}")
    assert resp.status_code == 200
    with app.app_context():
        assert SideComp.query.get(comp_id) is None


def test_route_player_register_succeeds(app, client, tournament):
    with app.app_context():
        p = _make_player()
        _confirm_event_registration(tournament.url, p.id)
        sc = SideComp(event=tournament.url, name="A", type="DUELING", registration_open=True)
        db.session.add(sc)
        db.session.commit()
        comp_id = sc.id
        login_as(client, p)

    resp = client.post(f"/_api/sidecomps/{comp_id}/register", json={})
    assert resp.status_code == 200

    with app.app_context():
        assert SideCompRegistration.query.filter_by(comp=comp_id, player=p.id).count() == 1


def test_route_player_register_requires_player_account(app, client, tournament):
    """Team accounts cannot self-register for side competitions."""
    from models import Team

    with app.app_context():
        t = Team(id="t_team", name="T", pw_hash="dummy_hash")
        t.set_password("p")
        db.session.add(t)
        db.session.commit()
        sc = SideComp(event=tournament.url, name="A", type="DUELING")
        db.session.add(sc)
        db.session.commit()
        comp_id = sc.id
        login_as(client, t)

    resp = client.post(f"/_api/sidecomps/{comp_id}/register", json={})
    assert resp.status_code == 403


def test_route_player_deregister_succeeds(app, client, tournament):
    with app.app_context():
        p = _make_player()
        _confirm_event_registration(tournament.url, p.id)
        sc = SideComp(event=tournament.url, name="A", type="DUELING")
        db.session.add(sc)
        db.session.flush()
        db.session.add(SideCompRegistration(comp=sc.id, player=p.id))
        db.session.commit()
        comp_id = sc.id
        login_as(client, p)

    resp = client.post(f"/_api/sidecomps/{comp_id}/deregister")
    assert resp.status_code == 200

    with app.app_context():
        assert SideCompRegistration.query.filter_by(comp=comp_id, player=p.id).count() == 0


def test_route_register_player_as_to_succeeds(app, client, tournament):
    with app.app_context():
        to_user = _make_player("to_user", "TO User")
        _make_to(tournament.url, to_user.id)
        target = _make_player("p_other", "Other")
        _confirm_event_registration(tournament.url, target.id)
        sc = SideComp(event=tournament.url, name="A", type="DUELING")
        db.session.add(sc)
        db.session.commit()
        comp_id = sc.id
        target_id = target.id
        login_as(client, to_user)

    resp = client.post(
        f"/_api/sidecomps/{comp_id}/register-player-as-to",
        json={"player_id": target_id},
    )
    assert resp.status_code == 200

    with app.app_context():
        reg = SideCompRegistration.query.filter_by(comp=comp_id, player=target_id).first()
        assert reg is not None
        assert reg.registered_by_to is True


def test_delete_tournament_cascades_sidecomp_registrations(app, client, tournament):
    """Deleting a tournament must remove SideCompRegistration rows before SideComp.

    Regression test: SideCompRegistration has a FK to sidecomps.id, so deleting
    side comps without first removing their registrations raises IntegrityError
    when SQLite foreign_keys=ON.
    """
    with app.app_context():
        to_user = _make_player("to_user", "TO User")
        target = _make_player("p_other", "Other")
        _make_to(tournament.url, to_user.id)
        _confirm_event_registration(tournament.url, target.id)
        sc = SideComp(event=tournament.url, name="A", type="DUELING")
        db.session.add(sc)
        db.session.flush()
        cat = SideCompCategory(comp=sc.id, name="Open")
        db.session.add(cat)
        db.session.flush()
        db.session.add(SideCompRegistration(comp=sc.id, player=target.id, category=cat.id))
        db.session.commit()
        comp_id = sc.id
        tournament_url = tournament.url
        login_as(client, to_user)

    resp = client.post(
        f"/_api/{tournament_url}/delete",
        data={"confirm_url": tournament_url},
    )
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["success"] is True

    with app.app_context():
        assert SideComp.query.get(comp_id) is None
        assert SideCompRegistration.query.filter_by(comp=comp_id).count() == 0
        assert SideCompCategory.query.filter_by(comp=comp_id).count() == 0


def test_route_eligible_players_marks_sidecomp_registered_players(app, client, tournament):
    with app.app_context():
        to_user = _make_player("to_user", "TO User")
        _make_to(tournament.url, to_user.id)
        p1 = _make_player("p1", "P1")
        p2 = _make_player("p2", "P2")
        _confirm_event_registration(tournament.url, p1.id)
        _confirm_event_registration(tournament.url, p2.id)
        sc = SideComp(event=tournament.url, name="A", type="DUELING")
        db.session.add(sc)
        db.session.flush()
        db.session.add(SideCompRegistration(comp=sc.id, player=p1.id))
        db.session.add(SideCompEntryNumber(tournament_url=tournament.url, player=p1.id, entry_number=1))
        db.session.commit()
        comp_id = sc.id
        login_as(client, to_user)

    resp = client.get(f"/_api/sidecomps/{comp_id}/eligible-players")
    assert resp.status_code == 200
    rows_by_id = {row["player_id"]: row for row in resp.get_json()}
    assert set(rows_by_id) == {"p1", "p2"}
    assert rows_by_id["p1"]["sidecomp_registered"] is True
    assert rows_by_id["p1"]["entry_number"] == 1
    assert rows_by_id["p2"]["sidecomp_registered"] is False
    assert rows_by_id["p2"]["entry_number"] is None


def test_route_eligible_players_returns_league_scoped_registrations(app, client, test_db):
    """A side comp on a league-linked tournament must surface league-scoped registrations.

    For league tournaments, PlayerRegistration rows have league_id set and event NULL,
    and team pseudonyms live on league-scoped TeamRegistration rows. The endpoint must
    resolve registrations through the tournament's scope rather than filtering by event
    directly.
    """
    from datetime import datetime, timedelta, timezone

    from app.domain.enums import TeamRegistrationStatus
    from models import League, Team, TeamRegistration, Tournament
    from tests.utils import make_registrable_config

    with app.app_context():
        cfg = make_registrable_config(team_registration_open=True, player_registration_open=True)
        league = League(url="lg", name="LG", registrable_config_id=cfg.id)
        db.session.add(league)
        db.session.flush()
        tourn = Tournament(
            url="lg-evt",
            name="League Event",
            start_date=datetime.now(timezone.utc),
            end_date=datetime.now(timezone.utc) + timedelta(days=1),
            league_id="lg",
        )
        db.session.add(tourn)
        db.session.flush()

        to_user = _make_player("lg_to", "LG TO")
        db.session.add(TO(user_id=to_user.id, user_type="player", event=None, league_id="lg"))

        team = Team(id="lg_team", name="LG Team", pw_hash="dummy_hash")
        db.session.add(team)
        db.session.flush()
        db.session.add(
            TeamRegistration(
                event=None,
                league_id="lg",
                team=team.id,
                pseudonym="LG Pseudonym",
                status=TeamRegistrationStatus.CONFIRMED,
            )
        )

        p1 = _make_player("lg_p1", "LG P1")
        db.session.add(
            PlayerRegistration(
                event=None,
                league_id="lg",
                player=p1.id,
                team=team.id,
                jersey_number="7",
                jersey_name="P1",
                status=RegistrationStatus.CONFIRMED,
            )
        )

        sc = SideComp(event=tourn.url, name="LG SC", type="DUELING")
        db.session.add(sc)
        db.session.commit()
        comp_id = sc.id
        login_as(client, to_user)

    resp = client.get(f"/_api/sidecomps/{comp_id}/eligible-players")
    assert resp.status_code == 200
    rows = resp.get_json()
    assert [row["player_id"] for row in rows] == ["lg_p1"]
    assert rows[0]["team_pseudonym"] == "LG Pseudonym"


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------


def _open_comp(tournament_url, name="A"):
    sc = SideComp(event=tournament_url, name=name, type="DUELING", registration_open=True)
    db.session.add(sc)
    db.session.commit()
    return sc


def test_create_category_succeeds(test_db, tournament):
    to_user = _make_player("to_user", "TO User")
    _make_to(tournament.url, to_user.id)
    sc = _open_comp(tournament.url)

    from app.services.sidecomp_service import SideCompService

    res = SideCompService.create_category(sc.id, actor_user_id=to_user.id, actor_user_type="player", name="  Novice  ")
    assert isinstance(res, Ok)
    assert res.unwrap().name == "Novice"


def test_create_category_non_to_forbidden(test_db, tournament):
    p = _make_player("not_to", "Non TO")
    sc = _open_comp(tournament.url)

    from app.services.sidecomp_service import SideCompService

    res = SideCompService.create_category(sc.id, actor_user_id=p.id, actor_user_type="player", name="Novice")
    assert isinstance(res, Err)
    assert res.unwrap_err().status_code == 403


def test_create_category_empty_name(test_db, tournament):
    to_user = _make_player("to_user", "TO User")
    _make_to(tournament.url, to_user.id)
    sc = _open_comp(tournament.url)

    from app.services.sidecomp_service import SideCompService

    res = SideCompService.create_category(sc.id, actor_user_id=to_user.id, actor_user_type="player", name="   ")
    assert isinstance(res, Err)
    assert res.unwrap_err().status_code == 400


def test_create_category_duplicate(test_db, tournament):
    to_user = _make_player("to_user", "TO User")
    _make_to(tournament.url, to_user.id)
    sc = _open_comp(tournament.url)

    from app.services.sidecomp_service import SideCompService

    SideCompService.create_category(sc.id, actor_user_id=to_user.id, actor_user_type="player", name="Novice")
    res = SideCompService.create_category(sc.id, actor_user_id=to_user.id, actor_user_type="player", name="Novice")
    assert isinstance(res, Err)
    assert res.unwrap_err().status_code == 400


def test_rename_category_succeeds(test_db, tournament):
    to_user = _make_player("to_user", "TO User")
    _make_to(tournament.url, to_user.id)
    sc = _open_comp(tournament.url)
    cat = SideCompCategory(comp=sc.id, name="Novice")
    db.session.add(cat)
    db.session.commit()

    from app.services.sidecomp_service import SideCompService

    res = SideCompService.rename_category(cat.id, actor_user_id=to_user.id, actor_user_type="player", name="Beginner")
    assert isinstance(res, Ok)
    assert SideCompCategory.query.get(cat.id).name == "Beginner"


def test_rename_category_collision(test_db, tournament):
    to_user = _make_player("to_user", "TO User")
    _make_to(tournament.url, to_user.id)
    sc = _open_comp(tournament.url)
    c1 = SideCompCategory(comp=sc.id, name="Novice")
    c2 = SideCompCategory(comp=sc.id, name="Pro")
    db.session.add_all([c1, c2])
    db.session.commit()

    from app.services.sidecomp_service import SideCompService

    res = SideCompService.rename_category(c2.id, actor_user_id=to_user.id, actor_user_type="player", name="Novice")
    assert isinstance(res, Err)
    assert res.unwrap_err().status_code == 400


def test_list_categories_ordered(test_db, tournament):
    sc = _open_comp(tournament.url)
    db.session.add_all([SideCompCategory(comp=sc.id, name="First"), SideCompCategory(comp=sc.id, name="Second")])
    db.session.commit()

    from app.services.sidecomp_service import SideCompService

    res = SideCompService.list_categories(sc.id)
    assert isinstance(res, Ok)
    assert [c.name for c in res.unwrap()] == ["First", "Second"]


def test_create_comp_with_categories(test_db, tournament):
    to_user = _make_player("to_user", "TO User")
    _make_to(tournament.url, to_user.id)

    from app.services.sidecomp_service import SideCompService

    res = SideCompService.create(
        tournament.url,
        actor_user_id=to_user.id,
        actor_user_type="player",
        name="Dueling",
        type="DUELING",
        categories=["Novice", "  ", "Pro"],
    )
    assert isinstance(res, Ok)
    names = {c.name for c in SideCompCategory.query.filter_by(comp=res.unwrap().id).all()}
    assert names == {"Novice", "Pro"}


def test_create_comp_with_duplicate_categories(test_db, tournament):
    to_user = _make_player("to_user", "TO User")
    _make_to(tournament.url, to_user.id)

    from app.services.sidecomp_service import SideCompService

    res = SideCompService.create(
        tournament.url,
        actor_user_id=to_user.id,
        actor_user_type="player",
        name="Dueling",
        type="DUELING",
        categories=["Novice", "Novice"],
    )
    assert isinstance(res, Err)
    assert res.unwrap_err().status_code == 400


def test_register_requires_category_when_categories_exist(test_db, tournament):
    p = _make_player()
    _confirm_event_registration(tournament.url, p.id)
    sc = _open_comp(tournament.url)
    db.session.add(SideCompCategory(comp=sc.id, name="Novice"))
    db.session.commit()

    from app.services.sidecomp_service import SideCompService

    res = SideCompService.register_player(sc.id, player_id=p.id)
    assert isinstance(res, Err)
    assert res.unwrap_err().status_code == 400


def test_register_rejects_foreign_category(test_db, tournament):
    p = _make_player()
    _confirm_event_registration(tournament.url, p.id)
    sc = _open_comp(tournament.url, "A")
    other = _open_comp(tournament.url, "B")
    foreign = SideCompCategory(comp=other.id, name="Pro")
    own = SideCompCategory(comp=sc.id, name="Novice")
    db.session.add_all([foreign, own])
    db.session.commit()

    from app.services.sidecomp_service import SideCompService

    res = SideCompService.register_player(sc.id, player_id=p.id, category_id=foreign.id)
    assert isinstance(res, Err)
    assert res.unwrap_err().status_code == 400


def test_register_stores_category(test_db, tournament):
    p = _make_player()
    _confirm_event_registration(tournament.url, p.id)
    sc = _open_comp(tournament.url)
    cat = SideCompCategory(comp=sc.id, name="Novice")
    db.session.add(cat)
    db.session.commit()

    from app.services.sidecomp_service import SideCompService

    res = SideCompService.register_player(sc.id, player_id=p.id, category_id=cat.id)
    assert isinstance(res, Ok)
    assert res.unwrap().category == cat.id


def test_register_ignores_category_when_none_exist(test_db, tournament):
    p = _make_player()
    _confirm_event_registration(tournament.url, p.id)
    sc = _open_comp(tournament.url)

    from app.services.sidecomp_service import SideCompService

    res = SideCompService.register_player(sc.id, player_id=p.id, category_id=999)
    assert isinstance(res, Ok)
    assert res.unwrap().category is None


def test_register_as_to_requires_category(test_db, tournament):
    to_user = _make_player("to_user", "TO User")
    target = _make_player("p_other", "Other")
    _make_to(tournament.url, to_user.id)
    _confirm_event_registration(tournament.url, target.id)
    sc = _open_comp(tournament.url)
    db.session.add(SideCompCategory(comp=sc.id, name="Novice"))
    db.session.commit()

    from app.services.sidecomp_service import SideCompService

    res = SideCompService.register_player_as_to(
        sc.id, actor_user_id=to_user.id, actor_user_type="player", player_id=target.id
    )
    assert isinstance(res, Err)
    assert res.unwrap_err().status_code == 400


def test_register_as_to_stores_category(test_db, tournament):
    to_user = _make_player("to_user", "TO User")
    target = _make_player("p_other", "Other")
    _make_to(tournament.url, to_user.id)
    _confirm_event_registration(tournament.url, target.id)
    sc = _open_comp(tournament.url)
    cat = SideCompCategory(comp=sc.id, name="Novice")
    db.session.add(cat)
    db.session.commit()

    from app.services.sidecomp_service import SideCompService

    res = SideCompService.register_player_as_to(
        sc.id, actor_user_id=to_user.id, actor_user_type="player", player_id=target.id, category_id=cat.id
    )
    assert isinstance(res, Ok)
    assert res.unwrap().category == cat.id


def _category_with_player(tournament, comp_name="A", cat_name="Novice", player_id="p_cat"):
    """Create an open comp with one category and one registered player in it."""
    p = _make_player(player_id, player_id.upper())
    _confirm_event_registration(tournament.url, p.id)
    sc = _open_comp(tournament.url, comp_name)
    cat = SideCompCategory(comp=sc.id, name=cat_name)
    db.session.add(cat)
    db.session.commit()

    from app.services.sidecomp_service import SideCompService

    SideCompService.register_player(sc.id, player_id=p.id, category_id=cat.id).unwrap()
    return sc, cat, p


def test_delete_category_empty_just_deletes(test_db, tournament):
    to_user = _make_player("to_user", "TO User")
    _make_to(tournament.url, to_user.id)
    sc = _open_comp(tournament.url)
    cat = SideCompCategory(comp=sc.id, name="Novice")
    db.session.add(cat)
    db.session.commit()

    from app.services.sidecomp_service import SideCompService

    # No players: mode is irrelevant.
    res = SideCompService.delete_category(cat.id, actor_user_id=to_user.id, actor_user_type="player")
    assert isinstance(res, Ok)
    assert SideCompCategory.query.get(cat.id) is None


def test_delete_category_deregister_mode(test_db, tournament):
    to_user = _make_player("to_user", "TO User")
    _make_to(tournament.url, to_user.id)
    sc, cat, p = _category_with_player(tournament)

    from app.services.sidecomp_service import SideCompService

    res = SideCompService.delete_category(cat.id, actor_user_id=to_user.id, actor_user_type="player", mode="deregister")
    assert isinstance(res, Ok)
    assert SideCompCategory.query.get(cat.id) is None
    assert SideCompRegistration.query.filter_by(comp=sc.id, player=p.id).count() == 0
    # Entry numbers are tournament-scoped and not reused: the row must persist.
    assert SideCompEntryNumber.query.filter_by(tournament_url=tournament.url, player=p.id).count() == 1


def test_delete_category_move_mode(test_db, tournament):
    to_user = _make_player("to_user", "TO User")
    _make_to(tournament.url, to_user.id)
    sc, cat, p = _category_with_player(tournament)
    target = SideCompCategory(comp=sc.id, name="Pro")
    db.session.add(target)
    db.session.commit()

    from app.services.sidecomp_service import SideCompService

    res = SideCompService.delete_category(
        cat.id, actor_user_id=to_user.id, actor_user_type="player", mode="move", target_category_id=target.id
    )
    assert isinstance(res, Ok)
    assert SideCompCategory.query.get(cat.id) is None
    reg = SideCompRegistration.query.filter_by(comp=sc.id, player=p.id).first()
    assert reg is not None
    assert reg.category == target.id


def test_delete_category_move_requires_target(test_db, tournament):
    to_user = _make_player("to_user", "TO User")
    _make_to(tournament.url, to_user.id)
    sc, cat, p = _category_with_player(tournament)

    from app.services.sidecomp_service import SideCompService

    res = SideCompService.delete_category(cat.id, actor_user_id=to_user.id, actor_user_type="player", mode="move")
    assert isinstance(res, Err)
    assert res.unwrap_err().status_code == 400


def test_delete_category_move_target_is_self(test_db, tournament):
    to_user = _make_player("to_user", "TO User")
    _make_to(tournament.url, to_user.id)
    sc, cat, p = _category_with_player(tournament)

    from app.services.sidecomp_service import SideCompService

    res = SideCompService.delete_category(
        cat.id, actor_user_id=to_user.id, actor_user_type="player", mode="move", target_category_id=cat.id
    )
    assert isinstance(res, Err)
    assert res.unwrap_err().status_code == 400


def test_delete_category_move_target_other_comp(test_db, tournament):
    to_user = _make_player("to_user", "TO User")
    _make_to(tournament.url, to_user.id)
    sc, cat, p = _category_with_player(tournament)
    other = _open_comp(tournament.url, "B")
    other_cat = SideCompCategory(comp=other.id, name="Pro")
    db.session.add(other_cat)
    db.session.commit()

    from app.services.sidecomp_service import SideCompService

    res = SideCompService.delete_category(
        cat.id, actor_user_id=to_user.id, actor_user_type="player", mode="move", target_category_id=other_cat.id
    )
    assert isinstance(res, Err)
    assert res.unwrap_err().status_code == 400


def test_delete_category_invalid_mode(test_db, tournament):
    to_user = _make_player("to_user", "TO User")
    _make_to(tournament.url, to_user.id)
    sc, cat, p = _category_with_player(tournament)

    from app.services.sidecomp_service import SideCompService

    res = SideCompService.delete_category(cat.id, actor_user_id=to_user.id, actor_user_type="player", mode="bogus")
    assert isinstance(res, Err)
    assert res.unwrap_err().status_code == 400


def test_route_create_category(app, client, tournament):
    with app.app_context():
        to_user = _make_player("to_user", "TO User")
        _make_to(tournament.url, to_user.id)
        sc = _open_comp(tournament.url)
        comp_id = sc.id
        login_as(client, to_user)

    resp = client.post(f"/_api/sidecomps/{comp_id}/categories", json={"name": "Novice"})
    assert resp.status_code == 200
    assert resp.get_json()["name"] == "Novice"


def test_route_create_category_non_to_403(app, client, tournament):
    with app.app_context():
        p = _make_player("not_to", "Non TO")
        sc = _open_comp(tournament.url)
        comp_id = sc.id
        login_as(client, p)

    resp = client.post(f"/_api/sidecomps/{comp_id}/categories", json={"name": "Novice"})
    assert resp.status_code == 403


def test_route_rename_category(app, client, tournament):
    with app.app_context():
        to_user = _make_player("to_user", "TO User")
        _make_to(tournament.url, to_user.id)
        sc = _open_comp(tournament.url)
        cat = SideCompCategory(comp=sc.id, name="Novice")
        db.session.add(cat)
        db.session.commit()
        cat_id = cat.id
        login_as(client, to_user)

    resp = client.patch(f"/_api/sidecomp-categories/{cat_id}", json={"name": "Beginner"})
    assert resp.status_code == 200
    assert resp.get_json()["name"] == "Beginner"


def test_route_delete_category_with_move(app, client, tournament):
    with app.app_context():
        to_user = _make_player("to_user", "TO User")
        _make_to(tournament.url, to_user.id)
        sc, cat, p = _category_with_player(tournament)
        target = SideCompCategory(comp=sc.id, name="Pro")
        db.session.add(target)
        db.session.commit()
        cat_id, target_id, comp_id, pid = cat.id, target.id, sc.id, p.id
        login_as(client, to_user)

    resp = client.post(
        f"/_api/sidecomp-categories/{cat_id}/delete",
        json={"mode": "move", "target_category_id": target_id},
    )
    assert resp.status_code == 200

    with app.app_context():
        assert SideCompCategory.query.get(cat_id) is None
        reg = SideCompRegistration.query.filter_by(comp=comp_id, player=pid).first()
        assert reg.category == target_id


def test_route_detail_includes_categories(app, client, tournament):
    with app.app_context():
        sc, cat, p = _category_with_player(tournament)
        comp_id, cat_id = sc.id, cat.id

    resp = client.get(f"/_api/sidecomps/{comp_id}")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["has_categories"] is True
    assert payload["categories"] == [{"id": cat_id, "name": "Novice", "registrant_count": 1}]
    assert payload["registrants"][0]["category_id"] == cat_id
    assert payload["registrants"][0]["category_name"] == "Novice"


def test_route_player_register_with_category(app, client, tournament):
    with app.app_context():
        p = _make_player()
        _confirm_event_registration(tournament.url, p.id)
        sc = _open_comp(tournament.url)
        cat = SideCompCategory(comp=sc.id, name="Novice")
        db.session.add(cat)
        db.session.commit()
        comp_id, cat_id, pid = sc.id, cat.id, p.id
        login_as(client, p)

    resp = client.post(f"/_api/sidecomps/{comp_id}/register", json={"category_id": cat_id})
    assert resp.status_code == 200

    with app.app_context():
        reg = SideCompRegistration.query.filter_by(comp=comp_id, player=pid).first()
        assert reg.category == cat_id


def test_route_player_register_missing_category_400(app, client, tournament):
    with app.app_context():
        p = _make_player()
        _confirm_event_registration(tournament.url, p.id)
        sc = _open_comp(tournament.url)
        db.session.add(SideCompCategory(comp=sc.id, name="Novice"))
        db.session.commit()
        comp_id = sc.id
        login_as(client, p)

    resp = client.post(f"/_api/sidecomps/{comp_id}/register", json={})
    assert resp.status_code == 400
