r"""URL surface snapshot test.

Locks the full (methods, rule) set of the Flask url_map against a
plain-text fixture. Intentionally ignores endpoint names - those change as
routes move between blueprints during the `_api.py` refactor. HEAD and
OPTIONS are excluded because Flask auto-generates them.

Each fixture line is ``<METHOD,METHOD,...> <RULE>``, sorted alphabetically.

When a PR intentionally adds, removes, or changes a URL, regenerate the
fixture from the repo root (lines below must stay flush-left so the
heredoc body is valid Python):

uv run python - <<'PY'
from pathlib import Path
from app import create_app

app = create_app(config={
    "TESTING": True,
    "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
    "WTF_CSRF_ENABLED": False,
    "SECRET_KEY": "fixture-gen",
})
lines = sorted(
    f"{','.join(sorted(r.methods - {'HEAD', 'OPTIONS'}))} {r.rule}"
    for r in app.url_map.iter_rules()
)
Path("tests/fixtures/url_surface.txt").write_text("\n".join(lines) + "\n")
PY
"""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.unit
def test_url_surface_unchanged(app):
    actual = sorted(
        f"{','.join(sorted(r.methods - {'HEAD', 'OPTIONS'}))} {r.rule}"
        for r in app.url_map.iter_rules()
    )
    fixture_path = Path(__file__).parent / "fixtures" / "url_surface.txt"
    expected = sorted(fixture_path.read_text().splitlines())

    assert actual == expected, (
        "URL surface drift detected. If the change is intentional, "
        "regenerate tests/fixtures/url_surface.txt per the docstring "
        "in this file and commit it alongside the routing change."
    )
