#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
UV="$SCRIPT_DIR/.venv/bin/uv"
OUTPUT="$SCRIPT_DIR/dist/pything-linux"

if [[ ! -x "$UV" ]]; then
    echo "Could not find executable uv at $UV" >&2
    exit 1
fi
if ! command -v cc >/dev/null 2>&1; then
    echo "A C compiler (cc) is required to build PYThing." >&2
    exit 1
fi

BUILD_DIR="$(mktemp -d)"
trap 'rm -rf "$BUILD_DIR"' EXIT
STAGE="$BUILD_DIR/payload"
mkdir -p "$STAGE/bin" "$SCRIPT_DIR/dist"
cc -O2 -std=c11 "$SCRIPT_DIR/launch.c" -o "$BUILD_DIR/launcher"
cp "$UV" "$STAGE/bin/uv"
cp -R "$SCRIPT_DIR/src" "$STAGE/src"
#cp "$SCRIPT_DIR/pyproject.toml" "$SCRIPT_DIR/uv.lock" "$SCRIPT_DIR/README.md" "$STAGE/"
find "$STAGE/src" -type d -name __pycache__ -prune -exec rm -rf {} +
find "$STAGE/src" -type d -name cache -prune -exec rm -rf {} + # TODO: stop using cache dirs in the first place and make apps use a global temp dir
find "$STAGE/src" -type f -name '*.pyc' -delete
chmod +x "$STAGE/bin/uv"

rm -rf "$OUTPUT"
"$BUILD_DIR/launcher" --pack "$STAGE" "$OUTPUT"
chmod +x "$OUTPUT"
echo "Built self-extracting Linux binary: $OUTPUT"
