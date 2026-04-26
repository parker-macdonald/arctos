"""Shared SQLAlchemy database instance for all Arctos models.

Import ``db`` from this module (or via ``app.models``) wherever ORM
models need to reference the extension object.
"""

from __future__ import annotations

from flask_sqlalchemy import SQLAlchemy

#: Single shared SQLAlchemy instance used by all models.
db = SQLAlchemy()


def init_db(database: SQLAlchemy) -> None:
    """No-op backwards-compatibility hook.

    Historically this project re-bound a global ``db`` variable at runtime.
    With a single shared ``db`` instance this is unnecessary; kept so that
    existing callers (e.g. ``init_db.py``) remain valid without modification.

    Args:
        database: The SQLAlchemy instance (ignored).
    """
    _ = database
