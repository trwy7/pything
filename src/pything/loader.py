"""Application loading and server startup."""

from __future__ import annotations

import datetime
import importlib
import importlib.util
import os
import sys
import threading
import time
import types
from http.server import ThreadingHTTPServer
from typing import Any

from . import state
from .depends import install_app_requirements
from .discovery import discover_apps, enabled_apps, overwritten_apps
from .server import Handler
from .web import Blueprint, _register_blueprint_routes
from .websocket import socket


def clock_thread() -> None:
    # Broadcast the current time periodically to connected websocket clients.
    while True:
        socket.emit("dt", datetime.datetime.now().isoformat())
        time.sleep(60)


def import_app(iappd: str) -> None:
    if not os.path.isdir(iappd):
        raise RuntimeError(
            "All apps must be directories, name your app as <name>/__init__.py"
        )
    state.logger.debug("Importing app %s", iappd)
    start_time = time.time()
    app_dir = os.path.abspath(iappd)
    # Apps under the source tree can use their normal package imports; external
    # app directories need a synthetic package namespace instead.
    source_root = os.path.dirname(os.path.abspath(state.__file__))
    try:
        is_source_app = os.path.commonpath((source_root, app_dir)) == source_root
    except ValueError:  # Different drives on Windows.
        is_source_app = False
    if is_source_app:
        module_name = os.path.relpath(app_dir, source_root).replace(os.sep, ".")
        iapp = importlib.import_module(module_name)
    else:
        # Give external apps a shared parent package so relative imports between
        # an app's modules work without colliding with regular package names.
        package_name = "_pything_apps"
        if package_name not in sys.modules:
            package = types.ModuleType(package_name)
            package.__path__ = []
            sys.modules[package_name] = package
        # A unique package name allows sibling imports while avoiding collisions
        # with built-in apps or other external app directories.
        module_name = f"{package_name}.{os.path.basename(app_dir)}"
        spec = importlib.util.spec_from_file_location(
            module_name,
            os.path.join(app_dir, "__init__.py"),
            submodule_search_locations=[app_dir],
        )
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Could not load app package from '{app_dir}'")
        iapp = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = iapp
        try:
            spec.loader.exec_module(iapp)
        except BaseException:
            sys.modules.pop(module_name, None)
            raise
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
    # Mount the app's declared routes under its own URL prefix.
    _register_blueprint_routes(iapp.app.blueprint, "/apps/" + iapp.app.id, iapp.app.id)
    # Optional HTML fragments are collected for the client to include later.
    if os.path.exists(os.path.join(iappd, "clientmod.html")):
        state.client_mods.append(
            (os.path.join(iapp.app.dirname, "clientmod.html").replace("\\", "/"), iapp.app)
        )
    if os.path.exists(os.path.join(iappd, "appmod.html")):
        state.app_mods.append(
            (os.path.join(iapp.app.dirname, "appmod.html").replace("\\", "/"), iapp.app)
        )
    # Apps without a launch endpoint stay hidden from the app launcher.
    for _methods, regex, _conv, _handler, app_id in state.routes:
        if (
            app_id == iapp.app.id
            and regex.pattern == "^/apps/" + iapp.app.id + "/launch$"
        ):
            state.logger.debug("%s has a launch route", iapp.app.id)
            iapp.app.hidden = False
            break


def dependency_order(
    app_ids: set[str], manifests: dict[str, dict[str, Any]]
) -> list[str]:
    """Return enabled apps with dependencies before their dependents."""
    ordered: list[str] = []
    visited: set[str] = set()
    visiting: list[str] = []

    def visit(app_id: str) -> None:
        if app_id in visited:
            return
        visiting.append(app_id)
        dependencies = manifests[app_id]["dependencies"]
        for dependency in sorted(
            set(dependencies["required"]) | set(dependencies["optional"])
        ):
            if dependency not in app_ids:
                continue
            if dependency in visiting:
                cycle = visiting[visiting.index(dependency) :] + [dependency]
                state.logger.error(
                    "Ignoring app dependency cycle: %s", " -> ".join(cycle)
                )
                continue
            visit(dependency)
        visiting.pop()
        visited.add(app_id)
        ordered.append(app_id)

    for app_id in sorted(app_ids):
        visit(app_id)
    return ordered


def main() -> None:
    print("Starting PYThing...")
    state.logger.debug("Init apps...")

    # Load enabled apps
    manifests = discover_apps()
    enabled = enabled_apps(manifests)

    # Report apps that cannot be loaded because a required dependency is absent
    # or itself cannot be loaded. Optional dependencies do not affect loading.
    unavailable: dict[str, str] = {}
    for app_id, manifest in manifests.items():
        for dependency in manifest["dependencies"]["required"]:
            if dependency not in manifests:
                unavailable[app_id] = (
                    f"required dependency '{dependency}' does not exist"
                )
                break
    changed = True
    while changed:
        changed = False
        for app_id in sorted(set(manifests) - set(unavailable)):
            for dependency in manifests[app_id]["dependencies"]["required"]:
                if dependency in unavailable:
                    unavailable[app_id] = (
                        f"required dependency '{dependency}' cannot be loaded"
                    )
                    changed = True
                    break
    for app_id, reason in sorted(unavailable.items()):
        state.logger.warning("Skipping app %s: %s", app_id, reason)
    state.discovered_app_manifests.clear()
    state.discovered_app_manifests.update(manifests)
    state.enabled_app_ids.clear()
    state.enabled_app_ids.update(enabled)
    state.overwritten_app_ids.clear()
    state.overwritten_app_ids.extend(overwritten_apps)
    enabled = dependency_order(enabled, manifests)
    # Install dependencies before importing apps, since imports may need them.
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
