#!/bin/bash
set -euo pipefail

# installs XCode CLI tools that homebrew uses to install/compile packages
# only run this if CLI tools are not already installed, otherwise it would raise an error
if ! xcode-select -p &> /dev/null; then
    xcode-select --install
    echo "Installed XCode CLI tools"
fi

# installs homebrew if it's not yet installed
if ! command -v brew &> /dev/null; then
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    echo "Installed Homebrew"
fi

directory=$(dirname "${BASH_SOURCE[0]}")

brew bundle --file="${directory}/Brewfile"
echo "Installed Homebrew packages"

if ! command -v cargo >/dev/null 2>&1; then
    rustup-init -y --default-toolchain stable
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
