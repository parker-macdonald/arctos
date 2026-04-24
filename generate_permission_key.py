#!/usr/bin/env python3
"""CLI utility that generates a tournament permission key.

The permission key is an HMAC-SHA256 digest of the tournament URL slug
signed with the application ``SECRET_KEY``.  Tournament Organisers
share this key with players so they can self-register for a tournament
that has restricted registration.

An explicit secret key may be provided as a second argument; otherwise
the key is read from the running Flask application configuration.

Usage:
    uv run generate_permission_key.py <url_slug> [secret_key]

Example:
    uv run generate_permission_key.py my-tournament
    uv run generate_permission_key.py my-tournament my-secret-key
"""

import sys
import os

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app
from app.utils.helpers import generate_permission_key


def main() -> None:
    """Parse CLI arguments and print the generated permission key.

    Reads ``url_slug`` and an optional ``secret_key`` from ``sys.argv``.
    When no secret key is supplied the Flask application is created so
    that ``SECRET_KEY`` can be read from the environment / config.

    Raises:
        SystemExit: If fewer than one positional argument is provided.
    """
    if len(sys.argv) < 2:
        print("Usage: python generate_permission_key.py <url_slug> [secret_key]")
        print("\nExample:")
        print("  python generate_permission_key.py my-tournament")
        print("  python generate_permission_key.py my-tournament my-secret-key")
        sys.exit(1)

    url_slug = sys.argv[1]
    secret_key = sys.argv[2] if len(sys.argv) > 2 else None

    if secret_key:
        # Use provided secret key
        key = generate_permission_key(url_slug, secret_key)
        print(f"Permission key for '{url_slug}': {key}")
    else:
        # Use Flask app's SECRET_KEY
        app = create_app()
        with app.app_context():
            key = generate_permission_key(url_slug)
            print(f"Permission key for '{url_slug}': {key}")


if __name__ == "__main__":
    main()
