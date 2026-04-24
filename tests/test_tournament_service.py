"""Tests for TournamentService.get_homepage_context."""

from datetime import datetime, timezone

import pytest

from app.services.tournament_service import TournamentService
from models import TO, Tournament, TeamRegistration, db
from tests.utils import make_registrable_config


@pytest.mark.unit
def test_homepage_context_includes_only_published_for_anonymous(test_db):
    """Anonymous users only see published tournaments in the homepage context."""
    pub = Tournament(
        url="pub",
        name="Published",
        start_date=datetime.now(timezone.utc),
        published=True,
        registrable_config_id=make_registrable_config().id,
    )
    priv = Tournament(
        url="priv",
        name="Private",
        start_date=datetime.now(timezone.utc),
        published=False,
        registrable_config_id=make_registrable_config().id,
    )
    db.session.add_all([pub, priv])
    db.session.commit()

    ctx = TournamentService.get_homepage_context(user=None)
    urls = {t.url for t in ctx["tournaments"]}
    assert "pub" in urls
    assert "priv" not in urls


@pytest.mark.unit
def test_homepage_context_team_counts_grouped_query(test_db):
    """team_counts only counts CONFIRMED registrations, not CANCELLED ones."""
    t_url = "counted"
    t = Tournament(
        url=t_url,
        name="Counted",
        start_date=datetime.now(timezone.utc),
        published=True,
        registrable_config_id=make_registrable_config().id,
    )
    db.session.add(t)
    db.session.add_all(
        [
            TeamRegistration(
                event=t_url, team="t1", pseudonym="T1", status="CONFIRMED"
            ),
            TeamRegistration(
                event=t_url, team="t2", pseudonym="T2", status="CONFIRMED"
            ),
            TeamRegistration(
                event=t_url, team="t3", pseudonym="T3", status="CANCELLED"
            ),
        ]
    )
    db.session.commit()

    ctx = TournamentService.get_homepage_context(user=None)
    assert ctx["team_counts"][t_url] == 2


@pytest.mark.unit
def test_homepage_context_includes_unpublished_for_to(test_db, player):
    """TOs can see their own unpublished tournaments in the homepage context."""
    # Ensure the player is a TO for an unpublished tournament
    priv_url = "priv-to"
    p = db.session.merge(player)
    priv = Tournament(
        url=priv_url,
        name="Private TO",
        start_date=datetime.now(timezone.utc),
        published=False,
        registrable_config_id=make_registrable_config().id,
    )
    db.session.add(priv)
    db.session.add(TO(user_id=p.id, user_type="player", event=priv_url))
    db.session.commit()

    ctx = TournamentService.get_homepage_context(user=p)
    urls = {t.url for t in ctx["tournaments"]}
    assert priv_url in urls
