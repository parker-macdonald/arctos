"""Tests for re-registration after rejection (no duplicate row created)."""

import pytest

from app.domain.enums import RegistrationStatus
from models import PlayerRegistration, db
from tests.utils import login_as


@pytest.mark.integration
def test_player_can_reregister_after_rejected_without_creating_duplicate_row(
    app, client, tournament, player, team
):
    """
    A rejected registration should be represented on the PlayerRegistration row.
    Re-registering should update that row (no duplicates) and set status back to pending/confirmed.
    """
    with app.app_context():
        t = db.session.merge(tournament)
        p = db.session.merge(player)
        tm = db.session.merge(team)
        tournament_url = t.url
        player_id = p.id
        team_id = tm.id
        login_as(client, p)

        # Seed a rejected registration row (simulating team decline)
        reg = PlayerRegistration(
            event=tournament_url,
            player=player_id,
            team=team_id,
            status="REJECTED",
            jersey_name="Alice",
            jersey_number="7",
        )
        db.session.add(reg)
        db.session.commit()
        reg_id = reg.id

    # Re-register (no team) should update the same row and become CONFIRMED
    resp = client.post(
        f"/{tournament_url}/register-player",
        data={"jersey_name": "Alice2", "jersey_number": "8"},
        follow_redirects=False,
    )
    assert resp.status_code in (301, 302, 303, 307, 308)

    with app.app_context():
        regs = PlayerRegistration.query.filter_by(
            event=tournament_url, player=player_id
        ).all()
        assert len(regs) == 1
        assert regs[0].id == reg_id
        assert regs[0].status == RegistrationStatus.CONFIRMED
        assert regs[0].jersey_name == "Alice2"
        assert regs[0].jersey_number == "8"
