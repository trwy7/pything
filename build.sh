#!/bin/bash
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
"$SCRIPT_DIR/.venv/bin/uv" run pyinstaller --name pything --onefile --add-data "$SCRIPT_DIR/src:src" --add-data "$SCRIPT_DIR/pyproject.toml:." --add-data "$SCRIPT_DIR/uv.lock:." --add-data "$SCRIPT_DIR/README.md:." --add-binary "$SCRIPT_DIR/.venv/bin/uv:bin" --hidden-import uv "$SCRIPT_DIR/launch.py"