#!/bin/bash
set -euo pipefail

directory=$(dirname "${BASH_SOURCE[0]}")

# Let uv pick the right CPython artifact for the host. Tracks the version
# pin in .python-version (currently 3.12), so updating that file is the
# one place to bump Python. Previous versions of this script hard-coded a
# per-platform slug like cpython-3.12.13-linux-x86_64-gnu, which broke on
# new architectures and silently rotted when Astral renamed distributions.
uv python install 3.12
echo "Installed Python (3.12)"

uv sync --group dev
uv run pre-commit install
echo "Installed pre-commit hooks"
