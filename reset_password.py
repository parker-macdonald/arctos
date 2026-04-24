"""CLI utility to reset a player or team account password.

Sets the target account's password to a cryptographically secure random
value and prints it to stdout.  Useful for account-recovery workflows
where the user cannot log in via OAuth.

Usage:
    python reset_password.py <username>

Example:
    python reset_password.py alice123
"""

import argparse
import secrets
import sys


def main() -> None:
    """Parse arguments, look up the account, and reset its password.

    Exits with a non-zero status if the username argument is missing,
    empty, or does not match any ``Player`` or ``Team`` record.

    Raises:
        SystemExit: On invalid arguments or when the account is not found.
    """
    parser = argparse.ArgumentParser(description="Set a user's password to a random value and print it.")
    parser.add_argument(
        "username",
        help="Player or team username (id)",
    )
    args = parser.parse_args()
    username = args.username.strip()
    if not username:
        print("Error: username is required", file=sys.stderr)
        sys.exit(1)

    from app import create_app
    from models import Player, Team, db

    app = create_app()
    with app.app_context():
        user = Player.query.filter_by(id=username).first()
        if not user:
            user = Team.query.filter_by(id=username).first()
        if not user:
            print(f"Error: no player or team found with id '{username}'", file=sys.stderr)
            sys.exit(1)
        password = secrets.token_urlsafe(16)
        user.set_password(password)
        db.session.commit()
        print(password)


if __name__ == "__main__":
    main()
