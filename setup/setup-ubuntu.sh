#!/bin/bash
set -euo pipefail

directory=$(dirname "${BASH_SOURCE[0]}")

xargs sudo apt-get install -y < "${directory}/apt-packages.txt"
echo "Installed apt packages"

bash -c "$(curl -LsSf https://astral.sh/uv/install.sh)"
echo "Installed uv"

if ! command -v cargo >/dev/null 2>&1; then
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable
    echo "Installed rustup + stable Rust toolchain"
fi

chmod +x "${directory}/setup-python.sh"
"${directory}/setup-python.sh"
