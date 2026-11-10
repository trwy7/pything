"""The App model and app registry helpers."""

from __future__ import annotations

import inspect
import json
import logging
import os
from collections.abc import Callable, Generator

from . import state
from .settings import ElementSetting, Setting
from .web import Blueprint
from .websocket import socket


class App:
    # TODO: docstring these functions to make it easier to build apps
    """
    Represents a pything app, use this class to create your app, and specify settings
    """

    def __init__(
        self,
        settings: list[Setting | ElementSetting],
    ):
        """Represents a PYThing app.
        
        Args:
            settings (list[Setting | ElementSetting]): A list of settings for the app.
        
        Attributes:
            id (str): The unique identifier for the app.
            display_name (str): The display name of the app.
            category (str): The category of the app.
            dir (str): The directory of the app.
            dirname (str): The name of the app's directory.
            cache_dir (Path): The cache directory for the app.
            data_dir (Path): The data directory for the app.
            config_dir (Path): The configuration directory for the app. Only use for data that cannot be stored in a setting, like a database or other large files.
            logger (Logger): The logger for the app.
            blueprint (Blueprint): The Flask blueprint for the app.
            settings (dict): A dictionary of settings for the app. Use this to access and modify settings.
        """
        stack = inspect.stack() # little janky, but works
        self.dir = os.path.dirname(os.path.abspath(stack[1].filename))
        self.dirname = os.path.basename(self.dir)
        self.cache_dir = state.CACHE_ROOT / "apps" / self.dirname
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir = state.DATA_ROOT / "apps" / self.dirname
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.config_dir = state.CONFIG_DIR / "apps" / self.dirname
        self.config_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = os.path.join(self.dir, "manifest.json")
        try:
            with open(manifest_path, encoding="utf-8") as manifest_file:
                manifest = json.load(manifest_file)
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"Failed to load manifest for app directory '{self.dir}'"
            ) from exc
        required_manifest_fields = {"id", "name", "codeowners", "category"}
        if not isinstance(manifest, dict) or not required_manifest_fields.issubset(
            manifest
        ):
            if not isinstance(manifest, dict):
                missing_fields = required_manifest_fields
            else:
                missing_fields = required_manifest_fields - manifest.keys()
            raise RuntimeError(
                f"Manifest for app directory '{self.dir}' is missing: "
                + ", ".join(sorted(missing_fields))
            )
        if not all(
            isinstance(manifest[field], str) for field in ("id", "name", "category")
        ):
            raise RuntimeError(
                f"Manifest for app directory '{self.dir}' has invalid metadata"
            )
        self.id = manifest["id"]
        self.display_name = manifest["name"]
        self.category = manifest["category"]
        state.apps[self.id] = self
        self.logger = logging.getLogger("pything.app." + self.id)
        state.logger.debug(
            f"Logger initialized for '{self.display_name}' with id '{self.id}'"
        )
        self.blueprint = Blueprint(
            self.id,
            __name__,
            static_folder=os.path.abspath(self.dir) + "/static"
            if os.path.isdir(os.path.join(self.dir, "static"))
            else None,
        )
        if self.blueprint.static_folder:
            state.app_static_dirs[self.id] = self.blueprint.static_folder

        self.settings = {s.id: s for s in settings}
        self.hidden = True  # updated on init
        self.listeners = {}
        self.startup_listeners: list[Callable] = []
        self.settingupdatelisteners: list[Callable] = []
        self.settingmodifylisteners: list[Callable] = []
        if not self.id in state.config:
            state.config[self.id] = {}
        schange = False
        for setting in settings:
            if not isinstance(setting, Setting):
                if isinstance(setting, ElementSetting):
                    continue
                raise ValueError(
                    "Settings must be instances of the Setting or ElementSetting class"
                )
            setting.app = self
            if not setting.id in state.config[self.id]:
                schange = True
                state.logger.debug(
                    f"Setting {setting.id} for {self.id} to default of {setting.default!s}"
                )
                state.config[self.id][setting.id] = setting.default
        if schange:
            state.logger.debug("Saving config with new default settings")
            state.save_config()

    def should_poll(self) -> bool:
        """
        Checks if at least one client has the App open
        """
        for client in state.clients.values():
            if client.app == self.id:
                return True
        return False

    def get_open_clients(self) -> Generator:
        for client in state.clients.values():
            if client.app == self.id:
                yield client

    def on(self, event: str):
        def decorator(func):
            self.listeners[event] = func
            return func

        return decorator

    def send(self, event: str, data, to: set[str] | str | None = None):
        state.logger.debug("serverapp>clientapp: %s > %s", self.id, event)
        if isinstance(to, set):
            for c in self.get_open_clients():
                if c.sid in to:
                    socket.emit("app_com", [self.id, event, data], to=c.sid)
            return
        if isinstance(to, str):
            for c in self.get_open_clients():
                if c.sid == to:
                    socket.emit("app_com", [self.id, event, data], to=c.sid)
            return
        for c in self.get_open_clients():
            socket.emit("app_com", [self.id, event, data], to=c.sid)

    def on_startup(self, func: Callable):
        self.startup_listeners.append(func)
        return func

    def startup(self):
        for listener in self.startup_listeners:
            self.logger.debug("Calling startup listener %s", listener.__name__)
            listener()

    def on_broadcast(self, event: str):
        def decorator(func):
            if event not in state.broadcast_listeners:
                state.broadcast_listeners[event] = []
            state.broadcast_listeners[event].append(func)
            return func

        return decorator

    def broadcast(self, event: str, *args, **kwargs):
        if event not in state.broadcast_listeners:
            self.logger.debug(
                "A broadcast to %s was sent by %s, but that event has no listeners, you can probably ignore this",
                event,
                self.id,
            )
            return
        for listener in state.broadcast_listeners[event]:
            listener(*args, **kwargs)
        self.logger.debug(
            "Broadcasting event %s to %d listeners",
            event,
            len(state.broadcast_listeners[event]),
        )

    def on_setting_update(self, func: Callable):
        self.logger.debug("Adding setting update listener %s", func.__name__)
        self.settingupdatelisteners.append(func)
        return func

    def on_setting_modify(self, func: Callable):
        self.logger.debug("Adding setting modify listener %s", func.__name__)
        self.settingmodifylisteners.append(func)
        return func


def get_apps():
    return state.apps


def stop_server(exit_code: int = 0):
    state.logger.info("Stopping server")
    event = "shutdown"
    socket.emit("shutdown")
    if event in state.broadcast_listeners:
        for listener in state.broadcast_listeners[event]:
            listener()
    os._exit(exit_code)
