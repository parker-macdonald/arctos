"""Shared test utility helpers."""


def login_as(client, user) -> None:
    """Authenticate *user* in the test client's session.

    Directly sets Flask-Login session keys rather than going through the
    login endpoint, so no password or network round-trip is needed.

    Args:
        client: A Flask test client instance.
        user: A :class:`~app.models.user.Player` or
            :class:`~app.models.user.Team` instance with a ``get_id()``
            method.
    """
    with client.session_transaction() as sess:
        sess["_user_id"] = user.get_id()
        sess["_fresh"] = True
