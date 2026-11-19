"""Built-in pages: client, settings and app management routes.

Importing this module registers its routes
"""

from __future__ import annotations

import shutil
import threading
from typing import Any

from . import state
from .app import App, stop_server
from .discovery import app_dependency_view, discover_apps, required_dependency_closure
from .web import Response, _set_current_app, redirect, render_template, request, route


restart_html = lambda x: (
    "<style>html { background: linear-gradient(350deg, #`   272727, #1f1f1f); color:"
    " #fff; }</style><h1 id='restarting'>PYThing is restarting...</h1><script>const params = new"
    " URLSearchParams(window.location.search); if (!params.has('from')) {"
    " setInterval(() => { fetch('/isready').then(response =>"
    f" response.text()).then(data => {{ window.location.href = '/{x}'; }}); }},"
    " 1000); } else { document.getElementById('restarting').style.textAlign = 'center'; document.getElementById('restarting').style.lineHeight = '99vh'; } </script>"
) # todo: make this a template

def restart() -> None:
    threading.Timer(0.5, stop_server, kwargs={"exit_code": state.RESTART_EXIT_CODE}).start()

@route("/isready")
def ct_isready() -> Response:
    return Response("OK", headers={"Access-Control-Allow-Origin": "*"})


@route("/")
def client_redirect() -> Response:
    return redirect("/client")


@route("/client")
def main_client() -> Response:

    _set_current_app(None)
    return render_template("client.html", mods=state.client_mods)


@route("/settings")
def settings_editor() -> Response:
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
def apps_editor() -> Response:
    manifests = discover_apps()
    return render_template(
        "apps.html",
        installed_apps=app_dependency_view(manifests),
        custom_hue=state.config.get("customizer", {}).get("hue", 151),
    )


@route("/apps", methods=("POST",))
def apps_set() -> str:
    manifests = discover_apps()
    selected = {app_id for app_id in manifests if f"app-{app_id}" in request.form}
    selected.update(
        app_id for app_id, manifest in manifests.items() if manifest["core"]
    )
    enabled = required_dependency_closure(selected, manifests)
    state.config[state.APP_CONFIG_ID] = {"disabled": sorted(set(manifests) - enabled)}
    state.save_config()

    restart()

    return restart_html("apps")


@route("/settings", methods=("POST",)) # TODO: upload/enable/disable/delete custom apps
def settings_set() -> Response:
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

@route("/customapps", methods=("POST",))
def custom_apps_set():
    # Only allow localhost access
    localhost = request.remote_addr in ("127.0.0.1", "::1")
    if not localhost:
        return Response("Access denied", status=403)
    if "apps" not in request.files:
        return Response("No files uploaded", status=400)
    for file in request.files.getlist("apps"):
        if not file.filename.endswith(".zip"): # bad way of checking type but it's fine for now because we only allow localhost
            return Response("Invalid file type", status=400)
        state.logger.info(f"Extracting custom app from {file.filename}")
        state.CUSTOM_APP_DIR.mkdir(parents=True, exist_ok=True)
        import zipfile  # lazy import

        with zipfile.ZipFile(file) as zf:
            # Read the manifest.json and check the "id" field
            if "manifest.json" not in zf.namelist():
                return Response("Invalid custom app: missing manifest.json", status=400)
            import json  # another lazy import

            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
            if "id" not in manifest:
                return Response("Invalid custom app: missing id in manifest.json", status=400)
            app_id = manifest["id"]
            # Check if the app is already installed
            if (state.CUSTOM_APP_DIR / app_id).exists():
                # overwrite the existing app
                state.logger.info(f"Overwriting custom app {app_id}")
                shutil.rmtree(state.CUSTOM_APP_DIR / app_id)
            # Extract the zip file to the custom apps directory
            zf.extractall(state.CUSTOM_APP_DIR / app_id)
    restart()
    return restart_html("customapps")