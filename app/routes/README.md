# `app/routes/` - Flask blueprints

Every HTTP handler lives here. Routes are organised into Flask
blueprints by topic, but they all share the same URL prefix:
**`/_api/`**.

Each file in this directory is a blueprint; its module-level docstring
states the topic it covers. New endpoints should go into the most
specific blueprint that fits; fall back to `_api.py` only if nothing
else is appropriate.

## What is a blueprint?

A [Flask blueprint](https://flask.palletsprojects.com/en/stable/blueprints/)
is a way to group related routes into a module that can be registered
on the app as a unit. Instead of every endpoint hanging off the global
`app` object, each topic gets its own `Blueprint(...)` object that
collects its own routes; `create_app()` then calls
`app.register_blueprint(bp, url_prefix="/_api")` once per blueprint.
The result is the same URL routing, but the code is split into
manageable files instead of one mega-module.

## Conventions

### URL prefix

All blueprints register with `url_prefix="/_api"`. The waivers blueprint
is the one exception, intentionally - the frontend links to
`/<event>/waiver` directly.

`/api/` (no underscore) is **reserved** for a hypothetical future
public API. Never use it.

### Return JSON

API routes return JSON `{success, ...}` payloads with HTTP status
codes:

- `200` on success
- `400` on validation failure
- `401` when unauthenticated (handled centrally by `login_manager.unauthorized_handler`)
- `403` when forbidden
- `404` when a resource isn't found

### Thin routes

The route handler should:

1. Authenticate (via `@login_required` or a custom decorator).
2. Parse the request - query params, form data, JSON body.
3. Call the service.
4. Convert the `Result` to JSON.

Workflow logic lives in [`app/services/`](../services/README.md). If
you're writing more than ~30 lines of route handler, consider whether
some of it belongs in a service.

```python
@bp.route("/<tournament_url>/register-team", methods=["POST"])
@login_required
def register_team_for_tournament(tournament_url: str):
    if not is_team(current_user):
        return jsonify({"success": False, "error": "Only teams can register"}), 403

    res = RegistrationService.register_team(
        tournament_url, current_user.id, request.form.get("pseudonym", "")
    )
    match res:
        case Ok(_):
            return jsonify({"success": True, "message": "Registered!"}), 200
        case Err(err):
            return jsonify({"success": False, "error": public_error_message(err)}), 400
```

### `@login_required` and the unauthorised handler

`login_manager.unauthorized_handler` (in `app/__init__.py`) returns a
JSON 401 for `/_api/...` paths instead of redirecting to a login URL -
this avoids CORS errors when the browser tries to follow the redirect.
Frontend code treats a 401 as "log in and retry".

For TO-only routes use the `@require_tournament_organizer` decorator
from `app.utils.decorators`.

## CORS in dev

When `ARCTOS_CORS_DEV=1`, `app/__init__.py` adds CORS headers and
handles `OPTIONS` preflight for every path. The browser sends the
session cookie because cookies are configured `SameSite=None; Secure`.
In production, nginx serves the SPA same-origin and CORS isn't needed.

## Adding a new endpoint

1. Pick the right blueprint or create a new one (rarely needed).
2. If you create a new blueprint, register it in
   `app/__init__.py::create_app`.
3. Use `@login_required` for anything that touches user data.
4. Validate inputs early; return `400` with a clear error message.
5. Delegate to a service for any non-trivial logic.
6. Write integration tests in [`tests/`](../../tests/README.md). The
   `client` fixture + `login_as(client, user)` from `tests/utils.py`
   covers most cases.
7. If your change adds, removes, or changes any URL or HTTP method,
   regenerate `tests/fixtures/url_surface.txt` (instructions in the
   docstring of `tests/test_url_surface.py`) and commit it in the
   same PR. The fixture is a deliberate gate against accidental URL
   drift, introduced for the in-flight `_api.py` refactor; it will be
   removed once that refactor is complete.

## When to promote a blueprint to a package

Default to a single file. Promote to a package only when one of these
triggers fires:

- The file crosses **~1,000 lines**.
- The file develops **3+ genuinely distinct sub-topics** that don't share
  state or helpers.
- Recurring **merge conflicts** because two contributors are routinely
  editing different parts of the same file.

A single trigger is sufficient. Conversely, a 1,200-line file whose
contents are tightly interrelated (one CRUD surface, shared helpers
throughout) can stay a single file.

### How to promote (mechanical)

1. `mkdir app/routes/<topic>/`.
2. `git mv app/routes/<topic>.py app/routes/<topic>/__init__.py`.
3. In `__init__.py`, keep the `bp = Blueprint(...)` definition and any
   helpers shared across submodules. Add
   `from . import <submodule1>, <submodule2>, ...` at the bottom so
   importing the package registers all handlers.
4. Create submodule files. Each starts with `from . import bp` (no new
   blueprint - they extend the existing one) and contains the routes
   for one sub-topic.
5. Run the URL surface snapshot test (`tests/test_url_surface.py`);
   confirm `app.url_map` is unchanged.
6. No external caller updates needed - `from app.routes.<topic> import bp`
   keeps working because `__init__.py` exposes it.

### What NOT to do

- Don't promote pre-emptively. A 200-line route file that *might* grow
  is not a candidate.
- Don't create new blueprints inside the package. Submodules share one
  Blueprint object so URL endpoint names stay stable across moves.

The :mod:`app.routes.tournaments` package is the canonical example.
