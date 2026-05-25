# Alembic migrations

This directory holds the versioned schema migrations for Arctos. Every
schema change after the initial baseline is shipped as a numbered
revision file under `versions/`.

## What is a migration, and why do we need them?

A **schema migration** is a small, versioned script that brings the
database from one shape to another (e.g. adding a column, renaming a
table, backfilling a value). Once code is shipped that *expects* a new
column, every running database - dev, staging, production, every
contributor's laptop - has to grow that column. A migration is how
that change is captured, code-reviewed, and applied deterministically
in the same order everywhere.

[Alembic](https://alembic.sqlalchemy.org/) is the migration tool that
ships with SQLAlchemy. It tracks which revisions have been applied to
a given database (in an `alembic_version` table), runs the ones that
have not, and supports auto-generating a draft revision by diffing the
SQLAlchemy models against the live schema. The
[Alembic tutorial](https://alembic.sqlalchemy.org/en/latest/tutorial.html)
and the
[autogenerate guide](https://alembic.sqlalchemy.org/en/latest/autogenerate.html)
are the two pages worth reading before writing your first migration.

`env.py` wires Alembic to `app.models.db`; `script.py.mako` is the
template used when generating new revisions; `versions/` holds the
numbered revision files starting from `0001_baseline.py`. The Alembic
config (`alembic.ini`) lives at the repository root.

## Day-to-day commands

Run everything via `uv run` so the project's pinned alembic version is used.

| Goal | Command (justfile shortcut in parens) |
|---|---|
| Stamp an existing DB at the current head (one-shot) | `uv run alembic stamp head` (`just db-baseline`) |
| Apply all outstanding migrations | `uv run alembic upgrade head` (`just db-migrate`, or `just db-migrate-safe` for backup-then-migrate) |
| Roll back the most recent migration | `uv run alembic downgrade -1` |
| Generate a new migration from model changes | `uv run alembic revision --autogenerate -m "snake_case_message"` (`just db-revision "..."`) |
| Inspect the current revision applied to the DB | `uv run alembic current` (`just db-current`) |
| Show the full revision history | `uv run alembic history` (`just db-history`) |

## Pointing alembic at a different database

By default the env file resolves to `instance/tournament.db` (matching how
Flask's instance-folder convention expands `sqlite:///tournament.db`).
Override with the `SQLALCHEMY_DATABASE_URI` environment variable:

```bash
SQLALCHEMY_DATABASE_URI=sqlite:////tmp/test.db uv run alembic upgrade head
```

## Documentation requirements

Every migration file **must** have a module-level docstring explaining *why* the change is being made.

Pre-commit hooks and CI may enforce this; in any case, treat it as a hard
review-time requirement.
