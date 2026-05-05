# `app/routes/` - Flask blueprints

Every HTTP handler lives here. Routes are organised into Flask
blueprints by topic, but they all share the same URL prefix:
**`/_api/`**.

## What's in here

| File | Blueprint | Topic |
|------|-----------|-------|
| `_api.py` | `_api` | The general JSON API for the SPA. The largest file in the project (~6k lines). |
| `auth.py` | `auth` | Logout, username availability, Google OAuth login + callback. (Login/register are handled inside the SPA + `_api`.) |
| `tournaments.py` | `tournaments` | Tournament management, schedule editing, recording / camera endpoints, finalisation. |
| `matches.py` | `matches` | Match operations: scoreboard, run, finalise, view. |
| `notes.py` | `notes` | Match-note CRUD (head refs only). |
| `registration.py` | `registration` | Team / player registration into tournaments and leagues. |
| `waivers.py` | `waivers` | Public waiver-document serving (intentionally outside `/_api/` so the frontend can link to a stable URL). |

New endpoints should go into the most specific blueprint that fits;
fall back to `_api.py` only if nothing else is appropriate.

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

## File-by-file quick reference

- **`_api.py`** - start here when looking for an existing endpoint.
  Tournament listing, match detail, points CRUD, schedule queries,
  rosters, head-ref permissions, notes, photos, profile updates,
  search, ...
- **`tournaments.py`** - TO-side workflows: create/edit tournaments,
  edit the schedule, manage cameras, finalise recordings. Boots the
  `Executor` used to run ffmpeg out-of-thread.
- **`matches.py`** - public scoreboard (used by OBS overlays), run
  match flow, finalise.
- **`notes.py`** - referee notes attached to matches and points.
- **`registration.py`** - register / unregister / re-register flows
  for both teams and players, plus league registration.
- **`auth.py`** - logout endpoint, username availability check, Google
  OAuth (login + callback). Login/register-with-password live in
  `_api.py`.
- **`waivers.py`** - serves the uploaded waiver PDF/file for an event
  or league. Falls back to the league waiver if the event belongs to
  one. Public, no auth.
