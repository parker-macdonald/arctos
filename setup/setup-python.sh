#!/bin/bash
set -euo pipefail

directory=$(dirname "${BASH_SOURCE[0]}")

# Detect platform and set Python version
if [[ "$(uname -s)" == "Darwin" && "$(uname -m)" == "arm64" ]]; then
    python_version="cpython-3.12.13-macos-aarch64-none"
elif [[ "$(uname -s)" == "Linux" && "$(uname -m)" == "x86_64" ]]; then
    python_version="cpython-3.12.13-linux-x86_64-gnu"
else
    echo "Unsupported platform. Only ARM64 macOS and x86_64 Ubuntu are supported."
    exit 1
fi

echo "Using Python version: ${python_version}"

uv python install ${python_version}
echo "Installed Python"

