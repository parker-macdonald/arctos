from __future__ import annotations

from flask_sqlalchemy import SQLAlchemy

# Single shared SQLAlchemy instance for all models.
db = SQLAlchemy()


def init_db(database: SQLAlchemy) -> None:
    """
    Backwards-compatibility hook.

    Historically this project re-bound a global `db` variable at runtime.
    With a single shared `db` instance this is unnecessary; keep as no-op so
    existing calls remain valid.
    """
    _ = database
