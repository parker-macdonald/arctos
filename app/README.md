# `app/` - Flask backend

This package is the entire Python backend. It is wired up by the
`create_app()` factory in [`__init__.py`](__init__.py) and exposed to
gunicorn through the top-level `run_app.py`.

## What's in here

| Path | Purpose |
|------|---------|
| `__init__.py` | The `create_app()` factory: config, blueprints, login, OAuth, CORS, SQLite pragmas, error handlers. |
| [`models/`](models/README.md) | SQLAlchemy ORM models. |
| [`routes/`](routes/README.md) | Flask blueprints - every route lives under `/_api/`. |
| [`services/`](services/README.md) | Application workflows; routes call into these. |
| [`utils/`](utils/README.md) | Cross-cutting helpers: scheduling, ASS DSL, datetime, video pipeline, auth helpers. |
| [`domain/`](domain/README.md) | Domain enums (`MatchStatus`, `ScheduleType`, ...). |
| [`serializers/`](serializers/README.md) | DB row -> JSON dict conversion for API responses. |
| `error_handlers.py` | Registers a single handler for `ArctosError` that picks JSON vs. HTML. |
| `error_values.py` | `Result`/`Option` types and the `@allow_Q` decorator (Rust-style errors-as-values). |
| `exceptions.py` | Domain exceptions (`ArctosError`, `NotFoundError`, `ValidationError`, ...). |
| `filters.py` | Jinja template filters. |

## How a request gets served

```
gunicorn ──-> run_app.py:app ──-> app.create_app() ──-> blueprint route
                                                    │
                                                    ├─-> validate request shape
                                                    ├─-> call service (in app/services/)
                                                    │       │
                                                    │       └─-> touch ORM models, commit
                                                    │
                                                    └─-> serialize Result -> JSON response
```

Four layers: **route -> service -> model -> db**. Keep routes thin; put
workflow logic in services; touch the DB through models (or the
[`dual_write`](services/README.md) helpers for join tables).

## What `create_app()` does

Walk-through of [`__init__.py`](__init__.py), top to bottom:

1. **Reads env vars** into `app.config`: `SECRET_KEY`, database URI,
   max upload size, OAuth client ID/secret, S3 video config, etc.
2. **Configures session cookies.** When `ARCTOS_CORS_DEV=1` it sets
   `SameSite=None; Secure` so the browser sends the session cookie on
   credentialed cross-origin requests from `dx serve`.
3. **Initialises extensions:** SQLAlchemy, Flask-Login, OAuth (via
   `authlib`), Flask-Executor (single-worker thread pool used to run
   ffmpeg finalisation off the request thread).
4. **Installs SQLite pragmas on every new connection** -
   `journal_mode=WAL`, `busy_timeout=30000`, and the load-bearing
   `foreign_keys=ON`. Without that last one SQLite ignores all
   `FOREIGN KEY` declarations and lets orphan rows accumulate.
5. **Registers blueprints:** `_api`, `auth`, `tournaments`, `matches`,
   `notes`, `registration`. They all use `url_prefix="/_api"`.
6. **Adds CORS middleware** scoped to `/_api/` (or all paths in dev),
   including `OPTIONS` preflight handling.
7. **Registers error handlers** (see `error_handlers.py`). An
   `ArctosError` becomes a JSON `{success: false, error: "..."}`
   response for API requests, or a flash + redirect for HTML paths.
8. **Boot-time work:** recomputes match schedules for every
   not-yet-complete tournament, and resumes interrupted YouTube uploads
   in background threads (best-effort; never blocks startup).

## Error Values

Most service methods return `Result[T, ArctosError]` from
[`error_values.py`](error_values.py). Routes pattern-match on it:

```python
from app.error_values import Ok, Err

res = RegistrationService.register_team(tournament_url, team_id, pseudonym)
match res:
    case Ok(_):
        return jsonify({"success": True, "message": "Registered!"}), 200
    case Err(err):
        return jsonify({"success": False, "error": public_error_message(err)}), 400
```

Inside services, the `.Q()` method is a Rust-style `?` operator:
short-circuits the function with the contained `Err`, but only when the
function is wrapped in `@allow_Q`. Don't call `.Q()` outside such a
function.

## Adding a new endpoint

1. Pick (or create) a blueprint in [`routes/`](routes/README.md).
2. If the work is non-trivial, add a method to a service in
   [`services/`](services/README.md). Return a `Result`.
3. Keep the route handler thin: parse request, call the service,
   convert `Result` to JSON.
4. Write a test in [`tests/`](../tests/README.md) - both a unit test
   for the service method and an integration test that hits the HTTP
   endpoint.

## Running

```bash
make run                 # gunicorn, 5 workers, on 0.0.0.0:8081
python run_app.py        # Werkzeug dev server on 127.0.0.1:5006
```

For everything else (frontend, migrations, tests) see the
[top-level README](../README.md).
