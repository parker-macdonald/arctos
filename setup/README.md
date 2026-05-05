# `setup/` - system bootstrap scripts

These scripts install the **system-level** dependencies required to
build and run Arctos. They're invoked through `make setup` (which
auto-detects your OS) - you shouldn't normally call them directly.

Application Python deps are not handled here; those live in
`pyproject.toml` and install via `make install` (`uv sync`).

## What's in here

| File | Used by | Installs |
|------|---------|----------|
| `setup-macos.sh` | `make setup` (on macOS) | XCode CLI tools, Homebrew, then everything in `Brewfile`, then calls `setup-python.sh`. |
| `setup-ubuntu.sh` | `make setup` (on Linux) | `apt` packages from `apt-packages.txt`, `uv` (via the upstream installer), then calls `setup-python.sh`. |
| `setup-python.sh` | called by both `setup-macos.sh` and `setup-ubuntu.sh` | A specific CPython 3.12 build via `uv python install`, then `uv sync --group dev`, then `pre-commit install`. |
| `Brewfile` | macOS | `git`, `uv`, `sqlite`. |
| `apt-packages.txt` | Ubuntu / Debian | `git`, `sqlite3`. |


Other targets:

| Target | What it does |
|--------|--------------|
| `make all` | Full setup chain: `setup` + `install` + `setup-frontend` |
| `make setup-os` | The same as `make setup` (OS-detected) |
| `make setup-macos` / `make setup-ubuntu` | Force a specific OS path |
| `make setup-python` | Just the Python toolchain step |
| `make install` | Skip system deps; only `uv sync` + pre-commit hooks |
| `make setup-frontend` | `cargo install dioxus-cli` (frontend deps) |

## Supported platforms

The scripts handle two platforms:

- **macOS on aarch64 (Apple Silicon).**
- **Ubuntu / Debian on x86_64.**

Other Linux distros work in principle if you install the equivalent of
`apt-packages.txt` manually and then run `make install`. Windows is
unsupported - use WSL.

## Adding a system dependency

- **macOS:** add a `brew "thing"` line to `Brewfile`.
- **Ubuntu:** add a package to `apt-packages.txt` (one per line, no
  comments - it's piped to `xargs sudo apt-get install -y`).

If a dependency is OS-agnostic and Python-only, add it to
`pyproject.toml` instead.

## Common issues

- **Homebrew install asks for sudo:** that's expected the first time;
  re-run `make setup`.
- **`uv` not found after install:** open a new shell - uv adds itself
  to `$PATH` via `~/.local/bin`, which a running shell may not have
  picked up.
- **Pre-commit hook install fails:** make sure you ran `make install`
  inside a git checkout (the script runs `pre-commit install`, which
  requires a `.git` directory).
- **Wrong Python version:** the script pins `cpython-3.12.13`. If `uv`
  fetches a different patch version, update `setup-python.sh`.
