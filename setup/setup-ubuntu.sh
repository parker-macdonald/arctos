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

chmod +x "${directory}/setup-python.sh"
"${directory}/setup-python.sh"
