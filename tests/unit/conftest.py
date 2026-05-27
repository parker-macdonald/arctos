"""
Unit-test conftest: provides a function-scoped Flask app for tests that
need to register routes dynamically (e.g. decorator tests).

The session-scoped ``app`` fixture in the root conftest is shared across
workers under pytest-xdist.  Registering new routes after the first HTTP
request raises an AssertionError in Flask 3.x.  A fresh app per function
sidesteps this entirely.
"""

import os
import tempfile

import pytest
from flask_login import FlaskLoginClient

from app import create_app
from models import db, init_db


@pytest.fixture()
def fresh_app():
    """Function-scoped Flask app with an isolated SQLite database.

    Suitable for tests that must register routes AFTER the app is created
    (e.g. route-decorator integration tests).  Each test gets a clean app
    with no prior requests, so Flask's "no new routes after first request"
    guard never fires.
    """
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    app_instance = create_app(
        config={
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_path}",
            "WTF_CSRF_ENABLED": False,
            "SECRET_KEY": "test-secret-key-fresh",
        }
    )
    app_instance.test_client_class = FlaskLoginClient

    with app_instance.app_context():
        db.create_all()
        init_db(db)
        db.session.commit()

    yield app_instance

    with app_instance.app_context():
        db.session.remove()
        db.drop_all()

    os.close(db_fd)
    if os.path.exists(db_path):
        os.unlink(db_path)
