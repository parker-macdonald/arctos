"""
Compatibility module.

Historically Arctos used a top-level `models.py`. Model definitions now live in
`app.models.*`. This file re-exports them so existing imports continue to work:

    from models import Tournament, Match, db
"""

from app.models import *  # noqa: F403
