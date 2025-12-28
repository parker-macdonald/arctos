def login_as(client, user):
    """
    Log in a user for tests using Flask-Login's session keys.
    """
    with client.session_transaction() as sess:
        sess["_user_id"] = user.get_id()
        sess["_fresh"] = True
