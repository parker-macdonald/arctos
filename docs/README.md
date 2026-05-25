# Building the Documentation

The documentation is built using [Sphinx](https://www.sphinx-doc.org/) inside a Docker container so that no local Python environment setup is required.

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) must be installed and running.
- `just` must be installed (`just setup` covers this on macOS / Ubuntu; otherwise see [just.systems](https://just.systems/)).

## Building

From the repo root:

```bash
just docs
```

This does two things automatically:

1. **Builds the Docker image** (`arctos-sphinx`) from `build_system/Dockerfile` if it does not already exist. The image contains Sphinx and all required extensions.
2. **Runs `sphinx-build`** inside that container with the repository root bind-mounted, producing HTML output at `docs/_build/html/`.

Open `docs/_build/html/index.html` in a browser to view the result.

## Other Recipes

| Recipe              | Description                                                  |
|---------------------|--------------------------------------------------------------|
| `just docs`         | Build (or rebuild) the Docker image and generate HTML docs   |
| `just docs-image`   | Build the Docker image only, without running a doc build     |
| `just docs-clean`   | Delete the `docs/_build/` output directory                   |

## Rebuilding the Docker Image

The Docker image is only built once and then cached by Docker. If you change `build_system/Dockerfile` (e.g. to add a new Sphinx extension), force a rebuild with:

```bash
just docs-image && just docs
```

Or remove the cached image manually and re-run `just docs`:

```bash
docker rmi arctos-sphinx
just docs
```
