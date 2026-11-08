"""Shared process state, configuration and registries.

Every other submodule depends on this one
"""

from __future__ import annotations

import logging
import os
import pickle
import shutil
import sys
from typing import Any

import truststore
from jinja2 import ChoiceLoader, Environment, FileSystemLoader

from .utils import CACHE_ROOT

truststore.inject_into_ssl()

DEVMODE = bool(os.environ.get("DEV", False))  # noqa: PLW1508

# Log to both the console and a file under CACHE_ROOT/pything/.
log_dir = os.path.join(CACHE_ROOT, "pything") if CACHE_ROOT else None
log_file = os.path.join(log_dir, "pything.log") if log_dir else None
log_handlers: list[logging.Handler] = [logging.StreamHandler()]
if log_file is not None:
    try:
        os.makedirs(log_dir, exist_ok=True)
        log_handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    except OSError:
        log_file = None  # fall back to console-only logging
logging.basicConfig(
    level=logging.DEBUG if DEVMODE else logging.INFO,
    handlers=log_handlers,
)
logger = logging.getLogger("pything")

if os.name == "nt":
    config_dir = os.path.join(os.environ["APPDATA"], "pything")
    old_data_path = os.path.join(os.environ["APPDATA"], "pything.pkl")
else:
    config_dir = os.path.join(os.path.expanduser("~"), ".config", "pything")
    old_data_path = os.path.join(os.path.expanduser("~"), ".config", "pything.pkl")
data_path = os.path.join(config_dir, "data.pkl")
APP_CONFIG_ID = "_apps"
RESTART_EXIT_CODE = 65
HOST = "127.0.0.1"
PORT = 5192

if os.path.exists(old_data_path) and not os.path.exists(data_path):
    os.makedirs(config_dir, exist_ok=True)
    shutil.move(old_data_path, data_path)

os.chdir(os.path.dirname(os.path.abspath(__file__)))  # sanity check

# Let apps load templates from their own directories
base_dir = os.path.dirname(os.path.abspath(__file__))
# Apps are imported by their top-level ``apps.*`` names, so expose the package
# directory as an import root both in source checkouts and installed wheels.
sys.path.insert(0, base_dir)

jinja_env = Environment(
    loader=ChoiceLoader(
        [
            FileSystemLoader(os.path.join(base_dir, "pages").replace("\\", "/")),
            FileSystemLoader(os.path.join(base_dir, "apps").replace("\\", "/")),
            FileSystemLoader(os.path.join(base_dir, "customapps").replace("\\", "/")),
        ]
    ),
    autoescape=False,
)


def save_config() -> None:
    os.makedirs(config_dir, exist_ok=True)
    with open(data_path, "wb") as cfw:
        pickle.dump(config, cfw)


if os.path.exists(data_path):
    with open(data_path, "rb") as cfr:
        config = pickle.load(cfr)
else:
    config = {}

# Determine whether to show command output
show_output = logger.isEnabledFor(logging.DEBUG)

# Registries live here so web/websocket/app code can share them without importing
# each other. Dicts/lists are mutated in place; never rebound after import.
apps: dict[str, Any] = {}
clients: dict[str, Any] = {}
broadcast_listeners: dict[str, list[Any]] = {}
client_mods: list[tuple[str, Any]] = []
app_mods: list[tuple[str, Any]] = []
app_static_dirs: dict[str, str] = {}
# (methods, regex, converters, handler, owning app id or None)
routes: list[tuple[set[str], Any, dict[str, Any], Any, str | None]] = []

READABLE_CATEGORIES = {
    "core": "Core",
    "musicprovider": "Music Providers",
    "device": "Devices",
    "music": "Music",
    "system": "System",
    "uncategorized": "Uncategorized",
}
