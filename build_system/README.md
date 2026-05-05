# `build_system/` — Docker-based build images

Build images used by tooling that should run the same way on every
contributor's machine.

## What's in here

| File | Purpose |
|------|---------|
| `Dockerfile` | Python 3.12 slim image with Sphinx, MyST, Furo, autodoc-typehints, plus the project's own dependencies installed from `pyproject.toml`. |

## How it's used

The container is consumed exclusively from
[`docs/Makefile`](../docs/Makefile). From the `docs/` directory:

```bash
make image     # build (or rebuild) the arctos-sphinx image
make html      # build the docs (also runs `make image` if needed)
make clean     # delete docs/_build
```

The full doc-building workflow is in
[`docs/README.md`](../docs/README.md).

## When to change the Dockerfile

- New Sphinx extension required by the docs build.
- Sphinx / MyST / Furo / autodoc-typehints version bump.
- Python base image upgrade.

After changing the Dockerfile, force a rebuild:

```bash
cd docs
make image && make html
```
