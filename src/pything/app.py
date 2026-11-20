"""The App model and app registry helpers."""

from __future__ import annotations

import inspect
import json
import logging
import os
import re
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import state
from .settings import ElementSetting, Setting
from .web import Blueprint
from .websocket import socket

if TYPE_CHECKING:
    from .websocket import Client

APP_ID_REGEX = re.compile(r"^[a-zA-Z0-9_]+$")

class App:
    """
    Represents a pything app, use this class to create your app, and specify settings
    """

    def __init__(
        self,
        settings: list[Setting | ElementSetting],
    ) -> None:
        """Represents a PYThing app.

        Args:
            settings (list[Setting | ElementSetting]): A list of settings for the app.

        Attributes:
            id (str): The unique identifier for the app.
            display_name (str): The display name of the app.
            category (str): The category of the app.
            dir (str): The directory of the app.
            dirname (str): The name of the app's directory.
            custom (bool): Whether the app is loaded from either custom-app directory.
            cache_dir (Path): The cache directory for the app.
            data_dir (Path): The data directory for the app.
            config_dir (Path): The configuration directory for the app. Only use for data that cannot be stored in a setting, like a database or other large files.
            logger (Logger): The logger for the app.
            blueprint (Blueprint): The Flask blueprint for the app.
            settings (dict): A dictionary of settings for the app. Use this to access and modify settings.
        """
        stack = inspect.stack()  # little janky, but works
        self.dir: str = os.path.dirname(os.path.abspath(stack[1].filename))
        self.dirname: str = os.path.basename(self.dir)
        app_path = Path(self.dir).resolve()
        source_root = Path(__file__).resolve().parent
        self.source = app_path.is_relative_to(source_root) # also very janky, undocumented intentionally
        custom_roots = (source_root / "customapps", state.CUSTOM_APP_DIR.resolve())
        self.custom = any(app_path.is_relative_to(root) for root in custom_roots)
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
        self.id: str = manifest["id"]
        if not APP_ID_REGEX.match(self.id):
            raise RuntimeError(
                f"Manifest for app directory '{self.dir}' has invalid id '{self.id}', must only contain alphanumeric characters and underscores"
            )
        self.cache_dir: Path = state.CACHE_ROOT / "apps" / self.id
        self.data_dir: Path = state.DATA_ROOT / "apps" / self.id
        self.config_dir: Path = state.CONFIG_DIR / "apps" / self.id
        self.display_name: str = manifest["name"]
        self.category: str = manifest["category"]
        self.version: int = int(manifest.get("version", 0))
        self.update_manifest_url: str | None = manifest.get("update_manifest_url")
        state.apps[self.id] = self
        self.logger: logging.Logger = logging.getLogger("pything.app." + self.id)
        if self.id in state.DEVAPPS:
            self.logger.setLevel(logging.DEBUG)
        state.logger.debug(
            f"Logger initialized for '{self.display_name}' with id '{self.id}'"
        )
        self.blueprint: Blueprint = Blueprint(
            self.id,
            __name__,
            static_folder=os.path.abspath(self.dir) + "/static"
            if os.path.isdir(os.path.join(self.dir, "static"))
            else None,
        )
        if self.blueprint.static_folder:
            state.app_static_dirs[self.id] = self.blueprint.static_folder

        self.settings: dict[str, Setting | ElementSetting] = {
            setting.id: setting for setting in settings
        }
        self.hidden: bool = True  # updated on init
        self.listeners: dict[str, Callable[..., Any]] = {}
        self.startup_listeners: list[Callable[..., Any]] = []
        self.settingupdatelisteners: list[Callable[..., Any]] = []
        self.settingmodifylisteners: list[Callable[..., Any]] = []
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

    def get_open_clients(self) -> Iterator[Client]:
        """
        Returns an iterator of all clients that have the App open
        """
        for client in state.clients.values():
            if client.app == self.id:
                yield client

    def on(self, event: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """
        Registers a listener for an event sent from the client app to the server app.
        The listener will be called with the data sent from the client app.
        You can send an event from the client app with the `send("event", data)` function in your apps javascript.
        """

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            self.listeners[event] = func
            return func

        return decorator

    def send(self, event: str, data: Any, to: set[str] | str | None = None) -> None:
        """
        Sends an event to the client app. If `to` is None, the event will be sent to all clients that have the App open. If `to` is a set of client IDs, the event will be sent to those clients. If `to` is a single client ID, the event will be sent to that client.
        You can recieve this event with the `on("event", (data) => {})` function in your apps javascript.
        """
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

    def on_startup(self, func: Callable[..., Any]) -> Callable[..., Any]:
        """
        Registers a listener for when the server starts up. This is called after all apps have been initialized, but before the server starts listening for connections. This is a good place to start background tasks
        """
        self.startup_listeners.append(func)
        return func

    def startup(self) -> None:
        """
        Calls all startup listeners. Do not call this directly, it is called by the server when it starts up.
        """
        for listener in self.startup_listeners:
            self.logger.debug("Calling startup listener %s", listener.__name__)
            listener()

    def on_broadcast(
        self, event: str
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """
        Listen for an event from another app. Your listener should run short, as it will block other apps from recieving the message until your listener returns. If you need to do something long, use a background thread.
        Broadcast names should be unique, like "music-set-playback-state" or "customizer-new-color". If you are broadcasting an event, make sure to document it in your app's README so other apps can listen for it.
        """

        # TODO: follow my own advice and standardize broadcast names, maybe even make a registry of them (probably not though)
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            if event not in state.broadcast_listeners:
                state.broadcast_listeners[event] = []
            state.broadcast_listeners[event].append(func)
            return func

        return decorator

    def broadcast(self, event: str, *args: Any, **kwargs: Any) -> None:
        """
        Broadcast an event to all apps that are listening for it. This is a way for apps to communicate with each other. The event will be sent to all apps that have registered a listener for it with `on_broadcast`.
        """
        # TODO: app-to-app communication by specifying the app id, instead of a broadcast
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

    def on_setting_update(self, func: Callable[..., Any]) -> Callable[..., Any]:
        self.logger.debug("Adding setting update listener %s", func.__name__)
        self.settingupdatelisteners.append(func)
        return func

    def on_setting_modify(self, func: Callable[..., Any]) -> Callable[..., Any]:
        self.logger.debug("Adding setting modify listener %s", func.__name__)
        self.settingmodifylisteners.append(func)
        return func


def stop_server(exit_code: int = 0) -> None:
    state.logger.info("Stopping server")
    event = "shutdown"
    socket.emit("shutdown")
    if event in state.broadcast_listeners:
        for listener in state.broadcast_listeners[event]:
            listener()
    os._exit(exit_code)
