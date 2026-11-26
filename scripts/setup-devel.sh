#!/bin/bash
set -e
# Check for uv
if ! command -v uv >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
fi
# Sync
uv sync
# Find dependencies
for papp in src/pything/apps/*; do
    manifest="$papp/manifest.json"
    mapfile -t deps < <(jq -r '(.requirements // [])[], (."requirements-linux" // [])[]' "$manifest")
    if (( ${#deps[@]} > 0 )); then
        # Install to venv
        uv pip install "${deps[@]}"
    fi
done