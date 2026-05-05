# `tests/` - pytest suite

The Python test suite. Tests run with pytest under uv. The companion
document [`TESTING.md`](../TESTING.md) at the repo root has the deeper
"how to write a good test" guide; this README is the file-by-file map.

## Running

```bash
make test          # everything
make unit          # unit tests only (-m unit)
make integration   # integration tests only (-m integration)

uv run pytest tests/ -k "registration"   # by name
uv run pytest tests/ --cov=app           # coverage
```

## Layout

```
tests/
├── conftest.py                     # shared fixtures (app, test_db, client, tournament, ...)
├── utils.py                        # make_registrable_config, login_as
├── test_basic.py
├── test_dsl_dependency_analyzer.py
├── test_dsl_parser.py
├── test_dynamic_scheduling.py
├── test_enums.py
├── test_error_handlers.py
├── test_error_values.py
├── test_matches_api.py
├── test_model_helpers.py
├── test_registration_flow.py
├── test_registration_reregister.py
│
├── unit/                            # marked @pytest.mark.unit
│   ├── test_cleanup_data_quality.py
│   ├── test_dependencies.py
│   ├── test_dual_write.py
│   ├── test_match_start_eligibility.py
│   ├── test_perm_key.py
│   ├── test_permissions.py
│   ├── test_phase1_schema.py
│   ├── test_schedule_import_export.py
│   ├── test_serializers.py
│   ├── test_services_unit.py
│   ├── test_tag_resolution.py
│   └── test_tournament_service.py
│
└── integration/                     # marked @pytest.mark.integration
    ├── test_dual_write_parity.py
    ├── test_match_start.py
    ├── test_permissions.py
    └── test_update_tags_recompute.py
```

## Markers

Mark every test:

```python
@pytest.mark.unit
def test_pure_logic(): ...

@pytest.mark.integration
def test_http_endpoint(client): ...

@pytest.mark.slow
def test_full_tournament(): ...
```

Configured in `pyproject.toml` under `[tool.pytest.ini_options]`. Strict
markers are on (`--strict-markers`), so an unknown marker is an error.

## Key fixtures (in `conftest.py`)

| Fixture | Scope | What it gives you |
|---------|-------|-------------------|
| `app` | session | Flask app wired to a tempfile SQLite DB |
| `test_db` | function | Drops/recreates tables before each test, opens an app context for the whole test |
| `client` | function | `FlaskLoginClient` test client |
| `tournament` | function | Published tournament with two fields, registration open |
| `player` | function | A `Player` row with password set |
| `team` | function | A `Team` row with password set |
| `team_registration` | function | Confirmed paid `TeamRegistration` |
| `head_ref_player` | function | Player on the tournament's head-ref allow-list |
| `seeded_teams` | function | Pre-seeds dummy team IDs that some tests reference by string |

`test_db` keeps the app context open, so fixtures that depend on it
should write to `db.session` directly - **don't** push another
`with app.app_context()`.

## Common patterns

### Creating a tournament

`Tournament` requires a `RegistrableConfig`. Use the helper:

```python
from tests.utils import make_registrable_config
from models import Tournament

cfg = make_registrable_config(team_registration_open=True)
t = Tournament(url="my-event", name="My Event", start_date=..., registrable_config_id=cfg.id)
db.session.add(t); db.session.commit()
```

### Logging a user in

```python
from tests.utils import login_as

login_as(client, player)        # injects Flask-Login session keys
client.post("/_api/...")
```

### Reading DB state after an HTTP call

The test client handles each request in its own context, so post-call
queries need a fresh context:

```python
resp = client.post("/_api/...")
assert resp.status_code == 200

with app.app_context():
    row = TeamRegistration.query.filter_by(...).first()
    assert row.status == "CONFIRMED"
```

### API returns JSON, not redirects

Routes under `/_api/` return JSON `{success, ...}`. Don't assert
`resp.status_code == 302` - assert `200` for success and `400` for
validation failure.

### `db.session.begin()` is wrong here

`test_db` already manages the transaction. Use plain
`db.session.add()` + `db.session.commit()`. Nesting `db.session.begin()`
will fail with "transaction already in progress".

## Adding a test

1. Pick `unit/` or `integration/` (or a top-level file) based on
   whether it touches HTTP / the DB.
2. Mark it (`@pytest.mark.unit` or `@pytest.mark.integration`).
3. Reuse fixtures from `conftest.py` - only write a new fixture if the
   shared ones don't fit.
4. Run `make test` (or `make unit` / `make integration`) before
   pushing.

For best practices and gotchas, read [`TESTING.md`](../TESTING.md).
