# Alembic migrations

This directory holds the versioned schema migrations for Arctos. Every
schema change after the initial baseline is shipped as a numbered
revision file under `versions/`.

## Layout

```
migrations/
  env.py              # Alembic environment — wires alembic to app.models.db
  script.py.mako      # Template used when generating new revisions
  versions/
    0001_baseline.py  # Empty baseline (existing schema, no upgrade ops)
    ...               # One file per subsequent revision
```

`alembic.ini` lives at the repository root.

## Day-to-day commands

Run everything via `uv run` so the project's pinned alembic version is used.

| Goal | Command (Makefile shortcut in parens) |
|---|---|
| Stamp an existing DB at the current head (one-shot) | `uv run alembic stamp head` (`make db-baseline`) |
| Apply all outstanding migrations | `uv run alembic upgrade head` (`make db-migrate`) |
| Roll back the most recent migration | `uv run alembic downgrade -1` |
| Generate a new migration from model changes | `uv run alembic revision --autogenerate -m "snake_case_message"` (`make db-revision MSG=...`) |
| Inspect the current revision applied to the DB | `uv run alembic current` |
| Show the full revision history | `uv run alembic history` |

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
