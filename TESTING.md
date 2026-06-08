# Testing

## Setup

Install dependencies including the test group:

```bash
uv sync --group test
```

## Running Tests

```bash
just test          # full suite
just unit          # unit tests only (fast, no DB)
just integration   # integration tests only
```

Without `just`:

```bash
uv run pytest tests/
uv run pytest tests/ -m unit
uv run pytest tests/ -m integration
```

Useful flags:

```bash
just test -k "registration"   # filter by name
just test --tb=long           # full tracebacks
```

## Coverage

Run the suite with coverage:

```bash
just coverage
just coverage -k "registration"   # filtered coverage run
```

`just coverage` disables the project-wide coverage floor so filtered
runs can report useful local numbers without failing because they only
exercise part of the app.

Run the CI-style coverage gate:

```bash
just coverage-check
```

Without `just`:

```bash
uv run pytest tests/ --cov=app --cov-report=term-missing --cov-fail-under=0
uv run pytest tests/ --cov=app --cov-report=term-missing --cov-fail-under=0 -k "registration"
```

Generate an HTML report (lands in `htmlcov/`, gitignored):

```bash
just coverage --cov-report=html
open htmlcov/index.html                  # or xdg-open on Linux
```

Coverage settings live under `[tool.coverage.*]` in `pyproject.toml`:

- **Source** is `app/` (tests, scripts, and migrations are not measured).
- **Branch coverage** is on, so untested `else` branches count as misses.
- **`fail_under = 30`** is a soft floor that catches significant
  regressions without blocking small fluctuations. CI enforces it with
  `just coverage-check`. Current actual coverage is around 33% (with
  branch coverage on); raise the floor when overall coverage grows.

## Structure

```
tests/
├── conftest.py          # shared fixtures (app, test_db, client, tournament, player, team, …)
├── utils.py             # helpers: make_registrable_config(), login_as()
├── test_basic.py
├── test_dependencies.py
├── test_match_start.py
├── test_matches_api.py
├── test_permissions.py
├── test_registration_flow.py
├── test_registration_reregister.py
├── test_tournament_service.py
├── test_update_tags_recompute.py
└── unit/
    ├── test_services_unit.py
    └── test_tag_resolution.py
```

## Markers

| Marker        | Meaning                          |
|---------------|----------------------------------|
| `unit`        | Pure logic, no database or HTTP  |
| `integration` | Hits the SQLite test DB via HTTP |
| `slow`        | Long-running tests               |

Mark a test:

```python
@pytest.mark.unit
def test_something():
    ...
```

## Key Fixtures

All fixtures are defined in `tests/conftest.py`.
- See [scope](https://docs.pytest.org/en/6.2.x/fixture.html#scope-sharing-fixtures-across-classes-modules-packages-or-session)


| Fixture             | Scope    | Description                                      |
|---------------------|----------|--------------------------------------------------|
| `app`               | session  | Flask app wired to a temporary SQLite file       |
| `test_db`           | function | Drops and recreates all tables before each test  |
| `client`            | function | `FlaskLoginClient` test client                   |
| `tournament`        | function | Published tournament with two fields             |
| `player`            | function | A `Player` row with password set                 |
| `team`              | function | A `Team` row with password set                   |
| `team_registration` | function | Confirmed, paid `TeamRegistration`               |
| `head_ref_player`   | function | Player whose ID is in `head_refs_allowed_list`   |

`test_db` keeps the app context open for the entire test, so ORM objects created by other fixtures stay attached to the session without needing extra `with app.app_context()` blocks.

## Utilities

**`make_registrable_config(**kwargs)`** — creates a `RegistrableConfig` with safe defaults (all registration closed). Pass keyword arguments to override specific fields.

**`login_as(client, user)`** — injects Flask-Login session keys so a user is considered authenticated without going through the login endpoint.

## Configuration

pytest options live in `pyproject.toml` under `[tool.pytest.ini_options]`.

---

## Best Practices

For general pytest guidance see the [official how-to guides](https://docs.pytest.org/en/stable/how-to/index.html). Project-specific rules are below.

**Mark every test** with `@pytest.mark.unit` or `@pytest.mark.integration` so it can be run in isolation.

**Use shared fixtures** from `tests/conftest.py` (`test_db`, `client`, `tournament`, `player`, `team`, …). Only write a new fixture when something genuinely test-specific is needed.

**One app context per test, owned by `test_db`** — `test_db` opens an app context that lives for the whole test. Fixtures that depend on `test_db` should write directly to the session; don't push a second `with app.app_context()` inside them.

```python
# good
@pytest.fixture
def my_thing(test_db):
    obj = MyModel(...)
    db.session.add(obj)
    db.session.commit()
    db.session.refresh(obj)
    return obj

# bad — second context closes before the test body runs
@pytest.fixture
def my_thing(app, test_db):
    with app.app_context():
        ...
```

**Reading DB state after HTTP calls** — the test client handles requests in its own context. Wrap post-request queries in `with app.app_context()`:

```python
resp = client.post("/_api/...")
assert resp.status_code == 200

with app.app_context():
    row = MyModel.query.filter_by(...).first()
    assert row.status == "CONFIRMED"
```

**API endpoints return JSON, not redirects** — all `/_api/` routes return `200` on success and `400` on validation failure. Don't assert for `302`.

**Creating tournaments** — `Tournament` requires a `registrable_config_id`. Use `make_registrable_config()`:

```python
from tests.utils import make_registrable_config

cfg = make_registrable_config(registration_open=True, team_registration_open=True)
t = Tournament(url="my-event", ..., registrable_config_id=cfg.id)
```

**Don't use `db.session.begin()`** — `test_db` already manages the transaction. Call `db.session.add()` / `db.session.commit()` directly.
