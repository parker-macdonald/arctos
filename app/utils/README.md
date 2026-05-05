# `app/utils/` - Helpers & Utility Functions

Helpers shared across routes, services, and models. The modules group
loosely by topic.

## Match scheduling and the ASS DSL

Arctos has a small Lisp-based DSL - the **A**rctos **S**chedule
**S**cript, or ASS - for expressing match dependencies and skip
conditions. A user-facing reference lives in
[`docs/arctos-schedule-script.md`](../../docs/arctos-schedule-script.md).

| File | What it does |
|------|--------------|
| `grammar.lark` | Lark grammar for the DSL. Expressions, atoms, lists, teams in `[brackets]`, matches in `{braces}`. |
| `parser.py` | Parses ASS expressions and evaluates them against the current tournament state (`(wins TEAM)`, `(winner MATCH)`, `(if COND TRUE FALSE)`, etc.). |
| `dsl_dependency_analyzer.py` | Walks an ASS expression and reports which matches it depends on, distinguishing direct (`(winner Match1)`) from skip-condition (`(is-skipped {Match2})`) dependencies. |
| `MatchGraph.py` | In-memory DAG of matches for topological sorting. Avoids repeated DB queries during schedule recomputation. |
| `scheduling.py` | Implements PROCEDURE - the per-match scheduling algorithm. SAFE finalises start time when the last dependency *starts*; FAST when all dependencies *complete*. Called on match create/edit and on match start/end. |
| `dependencies.py` | Resolves the linked-list-style `previous_match` / `next_match` relationships. |
| `match_ref_resolution.py` | Turns a CSV ref string into resolved team-ID slots - used by both API and import paths to keep the `refs` / `refs_initial` columns in sync. |

The DSL is the part of the codebase most likely to surprise newcomers.
The grammar is small (it fits in one screen) but the evaluation context
is large; start with `parser.py`'s top docstring and walk outward.

## Dates and times

| File | What it does |
|------|--------------|
| `datetime_helpers.py` | `normalize_datetime`, `to_iso_z`, etc. The codebase stores naive UTC; these helpers make conversion in/out predictable. |

## Authentication / users / permissions

| File | What it does |
|------|--------------|
| `helpers.py` | A general utility module. Most-used: `get_registrable_config(tournament)`, `can_head_ref_match(...)`, `is_valid_url_username`, `generate_permission_key` (HMAC of slug + secret, used for invite-only tournaments). |
| `user_helpers.py` | `is_player(user)`, `is_team(user)` - the right way to type-check a Flask-Login user. Avoid `user.__class__.__name__ == "Player"`. |
| `player_helpers.py` | Display-name resolution (jersey name -> registration -> player name -> ID). |
| `decorators.py` | Route decorators - `require_tournament_organizer` and friends. |
| `recording_retry.py` | Decides whether the current user is allowed to retry a failed finalisation (gated by an env var). |

## Cameras, footage, video

| File | What it does |
|------|--------------|
| `footage.py` | Finalisation worker: given a finished match, runs ffmpeg to assemble the recording and update the `Camera` row. Runs in a Flask-Executor thread. |
| `s3_video.py` | Upload to S3 / B2 and presigned URL generation. |
| `youtube_upload.py` | YouTube Data API v3 resumable uploads. |
| `user_uploads.py` | Direct uploads from camera operators (chunked, with manifest tracking). |
| `preview_store.py` | Filesystem-backed store for camera preview state - works across multiple gunicorn workers. |
| `camera_helpers.py` | HMAC-signed access keys so camera operators can use the recording page without a login. |

## Validation, responses, misc

| File | What it does |
|------|--------------|
| `name_validation.py` | Reserved characters in match names and team pseudonyms (kept in sync with the parser/exporter). |
| `responses.py` | `json_success` / `json_error` helpers. |
| `result_helpers.py` | Map `Result[T, ArctosError]` to a Flask JSON response. |
| `toml_helpers.py` | TOML parse/write for schedule import/export. |

## When to put something here vs. elsewhere

- **Used by one route only** -> keep it in the route file as a private helper.
- **Pure logic, used in one service** -> private helper inside the service.
- **Shared across routes / services / serializers** -> here.
- **Domain workflow with a clear name** -> make it a service in
  [`services/`](../services/README.md) instead of a util.

## Examples

**Resolving the registration config for either a standalone or league
tournament:**

```python
from app.utils.helpers import get_registrable_config

cfg = get_registrable_config(tournament)
if cfg and cfg.team_registration_open:
    ...
```

**Generating a permission key (used for invite-only tournaments):**

```bash
uv run generate_permission_key.py my-tournament
```

That CLI calls `app.utils.helpers.generate_permission_key`.

**Checking head-ref eligibility:**

```python
from app.utils.helpers import can_head_ref_match

if not can_head_ref_match(tournament_url, current_user.id, match=match):
    return jsonify({"error": "Not allowed"}), 403
```

**Recomputing the schedule after a match changes:**

```python
from app.utils.scheduling import recompute_all_match_times

recompute_all_match_times(tournament_url)
```
