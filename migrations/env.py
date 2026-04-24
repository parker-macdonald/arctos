"""Alembic environment for Arctos.

Loaded by Alembic's CLI on every invocation. Pulls the live SQLAlchemy
metadata from ``app.models`` so ``alembic revision --autogenerate`` produces
migrations that exactly match the running ORM schema, and resolves the
database URL the same way Flask does (instance-folder relative for SQLite).

The Flask application factory (:func:`app.create_app`) is intentionally
**not** invoked here. Alembic only needs ``db.metadata`` and a database URL;
running the full factory would also fire boot-time schedule recomputation,
OAuth client registration, and ``db.create_all()`` — none of which belong in
a migration tool, and ``create_all`` would race with the migration we are
about to apply.
"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, event, pool

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Side-effect import: registers every model class against ``db.metadata``.
# Must happen before ``target_metadata = db.metadata`` is evaluated below or
# autogenerate would diff the live database against an empty schema and try
# to drop every table.
from app.models import db  # noqa: E402


def _resolve_database_url() -> str:
    """Return the same SQLAlchemy URL the running Flask app would use.

    Resolution order:

    1. ``SQLALCHEMY_DATABASE_URI`` from the environment — lets CI and devs
       point alembic at a throwaway database without editing files.
    2. The default ``sqlite:///<repo>/instance/tournament.db``, mirroring
       Flask's instance-folder convention. The application config string
       ``sqlite:///tournament.db`` is interpreted by Flask-SQLAlchemy as
       *relative to the instance folder*; alembic has no concept of an
       instance folder, so we expand it to an absolute path here.
    """
    override = os.environ.get("SQLALCHEMY_DATABASE_URI")
    if override:
        return override
    instance_db = PROJECT_ROOT / "instance" / "tournament.db"
    return f"sqlite:///{instance_db}"


config = context.config
if not config.get_main_option("sqlalchemy.url"):
    config.set_main_option("sqlalchemy.url", _resolve_database_url())

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = db.metadata


def run_migrations_offline() -> None:
    """Render the migration as raw SQL without opening a DB connection.

    Used for ``alembic upgrade --sql`` style review workflows. ``render_as_batch``
    is enabled for SQLite because almost every ``ALTER`` requires the
    table-rebuild dance that batch mode encapsulates.
    """
    url = config.get_main_option("sqlalchemy.url") or ""
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=url.startswith("sqlite"),
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Apply migrations against a live database connection.

    Mirrors the application's per-connection ``PRAGMA foreign_keys = ON``
    (see ``app.set_sqlite_pragmas``) so DDL emitted by the migration is
    checked against existing data — otherwise a migration that adds a FK
    could pass here and fail in production. The pragma is installed via a
    ``connect`` event listener rather than ``connection.exec_driver_sql``
    because the latter would autobegin a transaction; SQLite silently
    ignores ``PRAGMA foreign_keys`` inside a transaction, AND the orphan
    transaction would swallow alembic's stamp/version INSERT on close.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    if connectable.dialect.name == "sqlite":

        @event.listens_for(connectable, "connect")
        def _enable_sqlite_fk(dbapi_connection, _connection_record):
            cur = dbapi_connection.cursor()
            try:
                cur.execute("PRAGMA foreign_keys = ON")
            finally:
                cur.close()

    with connectable.connect() as connection:
        is_sqlite = connection.dialect.name == "sqlite"
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=is_sqlite,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
