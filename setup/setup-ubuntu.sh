#!/bin/bash
set -euo pipefail

directory=$(dirname "${BASH_SOURCE[0]}")

xargs sudo apt-get install -y < "${directory}/apt-packages.txt"
echo "Installed apt packages"

bash -c "$(curl -LsSf https://astral.sh/uv/install.sh)"
echo "Installed uv"

chmod +x "${directory}/setup-python.sh"
"${directory}/setup-python.sh"
