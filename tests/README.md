# Test Suite

This directory contains the test suite for the tournament site application.

## Running Tests

To run all tests:
```bash
pytest
```

To run with verbose output:
```bash
pytest -v
```

To run a specific test file:
```bash
pytest tests/test_dynamic_scheduling.py
```

To run a specific test:
```bash
pytest tests/test_dynamic_scheduling.py::TestDynamicScheduling::test_basic_dynamic_scheduling
```

To run with coverage report:
```bash
pytest --cov=app --cov-report=html
```

## Test Structure

- `conftest.py`: Contains pytest fixtures used across all tests
- `test_dynamic_scheduling.py`: Tests for dynamic match scheduling functionality
- `test_basic.py`: Basic tests to verify the testing framework works

## Fixtures

Common fixtures available to all tests:

- `test_db`: Provides a temporary SQLite database for each test
- `client`: Flask test client with authentication support
- `tournament`: Creates a test tournament
- `player`: Creates a test player
- `team`: Creates a test team
- `team_registration`: Creates a team registration
- `head_ref_player`: Creates a head ref player

## Test Categories

Tests are marked with pytest markers:

- `@pytest.mark.unit`: Unit tests (fast, isolated)
- `@pytest.mark.integration`: Integration tests
- `@pytest.mark.slow`: Slow-running tests

Run tests by category:
```bash
pytest -m unit
pytest -m integration
```

