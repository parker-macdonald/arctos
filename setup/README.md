# `setup/` - system bootstrap scripts

These scripts install the **system-level** dependencies required to
build and run Arctos. They're invoked through `just setup` (which
auto-detects your OS) - you shouldn't normally call them directly.

Application Python deps are not handled here; those live in
`pyproject.toml` and install via `just install` (`uv sync`).

`just setup` dispatches to `setup-macos.sh` or `setup-ubuntu.sh` based
on your OS; both scripts install platform packages (from `Brewfile` or
`apt-packages.txt`), install `uv`, `just`, the Rust toolchain, and the
Dioxus CLI (`dx`), then chain into `setup-python.sh`. That last script
asks `uv` to install CPython 3.12 (uv picks the right artifact for the
host), runs `uv sync --group dev`, and installs the pre-commit hook.
See each script's header comments for the exact steps.

Other recipes:

| Recipe | What it does |
|--------|--------------|
| `just setup-macos` / `just setup-ubuntu` | Force a specific OS path |
| `just setup-python` | Just the Python toolchain step |
| `just install` | Skip system deps; only `uv sync` + pre-commit hooks |
| `just setup-frontend` | Install Dioxus CLI (`dx`) if it is missing |

## Supported platforms

The scripts handle two platforms:

- **macOS on aarch64 (Apple Silicon).**
- **Ubuntu / Debian on x86_64.**

Other Linux distros work in principle if you install the equivalent of
`apt-packages.txt` manually and then run `just install`. Windows is
unsupported - use WSL.

## Adding a system dependency

- **macOS:** add a `brew "thing"` line to `Brewfile`.
- **Ubuntu:** add a package to `apt-packages.txt` (one per line, no
  comments - it's piped to `xargs sudo apt-get install -y`).

If a dependency is OS-agnostic and Python-only, add it to
`pyproject.toml` instead.

## Common issues

- **Homebrew install asks for sudo:** that's expected the first time;
  re-run `just setup`.
- **`uv` or `just` not found after install:** open a new shell - both
  add themselves to `$PATH` via `~/.local/bin`, which a running shell
  may not have picked up.
- **Pre-commit hook install fails:** make sure you ran `just install`
  inside a git checkout (the script runs `pre-commit install`, which
  requires a `.git` directory).
- **Wrong Python version:** `setup-python.sh` asks `uv` for `3.12`. To
  pin a specific patch version, edit `.python-version` at the repo
  root (uv reads it on every invocation).
- **`cargo` not found after install:** on Ubuntu, the rustup installer
  writes to `~/.cargo/bin`. The setup script sources `~/.cargo/env`
  before running the rest, but a separate shell won't see it until you
  reopen the terminal (or run `. ~/.cargo/env` yourself).
