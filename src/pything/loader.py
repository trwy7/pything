"""Application loading and server startup."""

from __future__ import annotations

import datetime
import importlib
import os
import threading
import time
from http.server import ThreadingHTTPServer

from . import state
from .depends import install_app_requirements
from .discovery import discover_apps, enabled_apps
from .server import Handler
from .web import Blueprint, _register_blueprint_routes
from .websocket import socket


def clock_thread():
    while True:
        socket.emit("dt", datetime.datetime.now().isoformat())
        time.sleep(60)


def import_app(iappd: str):
    if not os.path.isdir(iappd):
        raise RuntimeError(
            "All apps must be directories, name your app as <name>/__init__.py"
        )
    state.logger.debug("Importing app %s", iappd)
    start_time = time.time()
    iapp = importlib.import_module(iappd.replace(os.sep, "."))
    end_time = time.time()
    state.logger.debug("Imported app %s in %.3f seconds", iappd, end_time - start_time)
    if not hasattr(iapp, "app"):
        raise RuntimeError(f"App {iappd} does not have an 'app' variable")
    # isinstance does not work for some reason, so we check for attributes
    if not (
        hasattr(iapp.app, "id")
        and hasattr(iapp.app, "blueprint")
        and hasattr(iapp.app, "display_name")
    ):
        raise TypeError(
            f"App {iappd} variable 'app' does not appear to be a valid App instance ({type(iapp.app)!s})"
        )
    # Make sure the blueprint is valid
    if not isinstance(iapp.app.blueprint, Blueprint):
        raise TypeError(
            f"App {iappd} variable 'app' has invalid blueprint ({type(iapp.app.blueprint)!s})"
        )
    _register_blueprint_routes(iapp.app.blueprint, "/apps/" + iapp.app.id, iapp.app.id)
    if os.path.exists(os.path.join(iappd, "clientmod.html")):
        state.client_mods.append(
            (os.path.join(iapp.app.id, "clientmod.html").replace("\\", "/"), iapp.app)
        )
    if os.path.exists(os.path.join(iappd, "appmod.html")):
        state.app_mods.append(
            (os.path.join(iapp.app.id, "appmod.html").replace("\\", "/"), iapp.app)
        )
    for _methods, regex, _conv, _handler, app_id in state.routes:
        if (
            app_id == iapp.app.id
            and regex.pattern == "^/apps/" + iapp.app.id + "/launch$"
        ):
            state.logger.debug("%s has a launch route", iapp.app.id)
            iapp.app.hidden = False
            break


def main() -> None:
    print("Starting PYThing...")
    state.logger.debug("Init apps...")

    # Load enabled apps
    manifests = discover_apps()
    enabled = sorted(enabled_apps(manifests))
    install_app_requirements(manifests[app_id]["directory"] for app_id in enabled)
    for app_id in enabled:
        import_app(manifests[app_id]["directory"])

    # Sort apps dict in place: other modules hold a reference to state.apps,
    # so the original rebinding of the global is expressed as an in-place sort.
    sorted_apps = dict(sorted(state.apps.items()))
    state.apps.clear()
    state.apps.update(sorted_apps)

    for loaded_app in state.apps.values():
        loaded_app.startup()

    # Start clock thread
    threading.Thread(target=clock_thread, daemon=True).start()

    # Start the server
    state.logger.info("Starting on %s:%s", state.HOST, state.PORT)
    server = ThreadingHTTPServer((state.HOST, state.PORT), Handler)
    server.daemon_threads = True
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
