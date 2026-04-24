from models import RegistrableConfig, db


def make_registrable_config(**kwargs) -> RegistrableConfig:
    """Create a RegistrableConfig with defaults suitable for testing.

    Must be called within an active app context (e.g. inside a test_db scope).
    """
    defaults = {
        "registration_open": False,
        "team_registration_open": False,
        "player_registration_open": False,
    }
    defaults.update(kwargs)
    cfg = RegistrableConfig(**defaults)
    db.session.add(cfg)
    db.session.flush()
    return cfg


def login_as(client, user):
    """
    Log in a user for tests using Flask-Login's session keys.
    """
    with client.session_transaction() as sess:
        sess["_user_id"] = user.get_id()
        sess["_fresh"] = True
