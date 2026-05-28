#!/bin/bash
set -euo pipefail

directory=$(dirname "${BASH_SOURCE[0]}")

xargs sudo apt-get install -y < "${directory}/apt-packages.txt"
echo "Installed apt packages"

bash -c "$(curl -LsSf https://astral.sh/uv/install.sh)"
echo "Installed uv"

# Install just into ~/.local/bin so it lands on the same PATH as uv.
# Apt has just on 22.10+ but not on older LTS, so prefer the upstream
# installer for consistency across hosts.
if ! command -v just &> /dev/null; then
    mkdir -p "${HOME}/.local/bin"
    curl --proto '=https' --tlsv1.2 -sSf https://just.systems/install.sh \
        | bash -s -- --to "${HOME}/.local/bin"
    echo "Installed just"
fi

if ! command -v cargo >/dev/null 2>&1; then
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable
    echo "Installed rustup + stable Rust toolchain"
fi

# Ensure cargo is on PATH for the rest of this script even when rustup was
# just installed (rustup-init writes ~/.cargo/bin to PATH via ~/.cargo/env but
# the current shell hasn't picked it up yet).
# shellcheck disable=SC1091
[ -f "$HOME/.cargo/env" ] && . "$HOME/.cargo/env"

if ! command -v dx >/dev/null 2>&1; then
    cargo install dioxus-cli
    echo "Installed Dioxus CLI (dx)"
fi

chmod +x "${directory}/setup-python.sh"
"${directory}/setup-python.sh"
