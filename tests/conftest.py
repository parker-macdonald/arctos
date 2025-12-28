"""
Pytest configuration and fixtures for testing the tournament site.
"""

import pytest
import tempfile
import os
from datetime import datetime, timedelta, timezone
from flask import Flask
from flask_login import FlaskLoginClient

# Import app components
from app import create_app
from models import (
    db,
    init_db,
    Tournament,
    Match,
    Player,
    Team,
    TeamRegistration,
    PlayerRegistration,
    Point,
    HeadRef,
)


@pytest.fixture(scope="session")
def app():
    """Create app instance with testing configuration and temporary database."""
    # Create temporary database file for the entire test session
    db_fd, db_path = tempfile.mkstemp(suffix=".db")

    # Create app with test database from the start
    app_instance = create_app(
        config={
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_path}",
            "WTF_CSRF_ENABLED": False,
            "SECRET_KEY": "test-secret-key",
        }
    )

    # Initialize database
    with app_instance.app_context():
        db.create_all()
        init_db(db)
        db.session.commit()

    yield app_instance

    # Cleanup
    with app_instance.app_context():
        db.session.remove()
        db.drop_all()

    os.close(db_fd)
    if os.path.exists(db_path):
        os.unlink(db_path)


@pytest.fixture(scope="function")
def test_db(app):
    """Ensure clean database state for each test."""
    with app.app_context():
        # Drop all and recreate to ensure clean state for each test
        db.drop_all()
        db.create_all()
        init_db(db)
        db.session.commit()
        yield db
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app, test_db):
    """Create a test client."""
    app.test_client_class = FlaskLoginClient
    with app.test_client() as client:
        with app.app_context():
            yield client


@pytest.fixture
def tournament(app, test_db):
    """Create a test tournament."""
    with app.app_context():
        tourn = Tournament(
            url="test-tournament",
            name="Test Tournament",
            start_date=datetime.now(timezone.utc),
            end_date=datetime.now(timezone.utc) + timedelta(days=1),
            location="Test Location",
            num_fields=2,
            n_max_teams=8,
            max_team_size_roster=10,
            max_team_size_field=7,
            max_field_size=14,
            published=True,
            schedule_published=True,
            registration_open=True,
            head_refs_allowed_list="test_ref1,test_ref2",
        )
        db.session.add(tourn)
        db.session.commit()
        # Store the URL as a simple attribute (already loaded)
        tourn_url = tourn.url
        # Make tournament accessible by storing URL as instance attribute
        # This prevents DetachedInstanceError when accessed in different app contexts
        return tourn


@pytest.fixture
def player(app, test_db):
    """Create a test player."""
    with app.app_context():
        player = Player(
            id="test_player",
            name="Test Player",
            pw_hash="dummy_hash",
            phone="1234567890",
        )
        player.set_password("testpass")
        db.session.add(player)
        db.session.commit()
        return player


@pytest.fixture
def team(app, test_db):
    """Create a test team."""
    with app.app_context():
        team = Team(id="test_team", name="Test Team", pw_hash="dummy_hash")
        team.set_password("testpass")
        db.session.add(team)
        db.session.commit()
        return team


@pytest.fixture
def team_registration(app, test_db, tournament, team):
    """Create a team registration."""
    with app.app_context():
        reg = TeamRegistration(
            event=tournament.url,
            team=team.id,
            pseudonym="Test Team Pseudonym",
            status="CONFIRMED",
            paid=True,
        )
        db.session.add(reg)
        db.session.commit()
        return reg


@pytest.fixture
def head_ref_player(app, test_db, tournament):
    """Create a head ref player."""
    with app.app_context():
        player = Player(id="test_ref1", name="Head Ref Player", pw_hash="dummy_hash")
        player.set_password("testpass")
        db.session.add(player)
        db.session.commit()
        return player


def create_match(
    tournament_url,
    name,
    field,
    nominal_start_time,
    dynamic=True,
    team1_initial=None,
    team2_initial=None,
    nominal_length=60,
):
    """Helper function to create a match."""
    match = Match(
        name=name,
        event=tournament_url,
        field=field,
        nominal_start_time=nominal_start_time,
        schedule_type="DYNAMIC" if dynamic else "STATIC",
        team1_initial=team1_initial,
        team2_initial=team2_initial,
        nominal_length=nominal_length,
        status="NOT_STARTED",
        set_type="SETS",
    )
    db.session.add(match)
    db.session.flush()
    return match
