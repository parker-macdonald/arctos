#!/usr/bin/env python3
"""
generate permission keys to create new tournaments. uses app secret key. if none is passed.

Usage:
    uv run generate_permission_key.py <url_slug> [secret_key]

"""

import sys
import os

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask
from app import create_app
from app.utils.helpers import generate_permission_key


def main():
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
