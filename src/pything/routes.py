"""Built-in pages: client, settings and app management routes.

Importing this module registers its routes
"""

from __future__ import annotations

import os
import threading
from typing import Any

from . import state
from .app import App, stop_server
from .discovery import app_dependency_view, discover_apps, required_dependency_closure
from .web import Response, redirect, render_template, request, route


@route("/isready")
def ct_isready():
    return Response("OK", headers={"Access-Control-Allow-Origin": "*"})


@route("/")
def client_redirect():
    return redirect("/client")


@route("/client")
def main_client():
    from .web import _set_current_app

    _set_current_app(None)
    return render_template("client.html", mods=state.client_mods)


@route("/settings")
def settings_editor():
    # sort and hide apps with no visible settings, beware of ai slop
    sapps: dict[str, list[App]] = {}
    for app in state.apps.values():
        if not any(not s.hidden for s in app.settings.values()):
            continue
        if not app.category in sapps:
            sapps[app.category] = []
        sapps[app.category].append(app)
    sapps = {
        category: sorted(category_apps, key=lambda a: a.display_name)
        for category, category_apps in sorted(
            sapps.items(),
            key=lambda item: (item[0] == "uncategorized", item[0].casefold()),
        )
    }
    # end ai
    return render_template(
        "settings.html",
        apps=sapps,
        readable_categories=state.READABLE_CATEGORIES,
        custom_hue=state.config.get("customizer", {}).get("hue", 151),
    )


@route("/apps", methods=("GET",))
def apps_editor():
    manifests = discover_apps()
    return render_template(
        "apps.html",
        installed_apps=app_dependency_view(manifests),
        custom_hue=state.config.get("customizer", {}).get("hue", 151),
    )


@route("/apps", methods=("POST",))
def apps_set():
    manifests = discover_apps()
    selected = {app_id for app_id in manifests if f"app-{app_id}" in request.form}
    selected.update(
        app_id for app_id, manifest in manifests.items() if manifest["core"]
    )
    enabled = required_dependency_closure(selected, manifests)
    state.config[state.APP_CONFIG_ID] = {"disabled": sorted(set(manifests) - enabled)}
    state.save_config()

    def restart() -> None:
        stop_server(exit_code=state.RESTART_EXIT_CODE)

    threading.Timer(0.5, restart).start()
    return (
        "<style>html { background: linear-gradient(350deg, #272727, #1f1f1f); color:"
        " #fff; }</style><h1 id='restarting'>PYThing is restarting...</h1><script>const params = new"
        " URLSearchParams(window.location.search); if (!params.has('from')) {"
        " setInterval(() => { fetch('/apps').then(response =>"
        " response.text()).then(data => { window.location.href = '/settings'; }); },"
        " 1000); } else { document.getElementById('restarting').style.textAlign = 'center'; document.getElementById('restarting').style.lineHeight = '99vh'; } </script>"
    )


@route("/settings", methods=("POST",))
def settings_set():
    state.logger.debug("Got new settings: %s", request.form)
    settings_changed = False
    for app in state.apps.values():
        changed: dict[str, Any] = {}
        for setting in app.settings.values():
            if f"{app.id}-{setting.id}" in request.form:
                nd = request.form[f"{app.id}-{setting.id}"]
                state.logger.debug(f"Setting '{app.id}' > '{setting.id}' to {nd!s}")
                match setting.type:
                    case "bool":
                        nd = nd == "on"
                    case "int":
                        nd = int(nd)
                        if setting.min_value is not None and nd < setting.min_value:
                            raise ValueError(
                                f"Value for int setting '{setting.id}' is below minimum of {setting.min_value}"
                            )
                        if setting.max_value is not None and nd > setting.max_value:
                            raise ValueError(
                                f"Value for int setting '{setting.id}' is above maximum of {setting.max_value}"
                            )
                    case "float":
                        nd = float(nd)
                        if setting.min_value is not None and nd < setting.min_value:
                            raise ValueError(
                                f"Value for float setting '{setting.id}' is below minimum of {setting.min_value}"
                            )
                        if setting.max_value is not None and nd > setting.max_value:
                            raise ValueError(
                                f"Value for float setting '{setting.id}' is above maximum of {setting.max_value}"
                            )
                    case "select":
                        if nd not in setting.options:
                            raise ValueError(
                                f"Invalid value for select setting '{setting.id}'"
                            )
                state.logger.debug(f"Setting as {nd}")
                if setting.get_value() != nd:
                    changed[setting.id] = nd
                    setting.set_value(nd, persist=False)
                    settings_changed = True
        if changed:
            for sl in app.settingupdatelisteners:
                sl(changed)
    if settings_changed:
        state.save_config()
    return redirect("/settings")
