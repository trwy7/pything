import pip_system_certs.wrapt_requests

pip_system_certs.wrapt_requests.inject_truststore()
import os
import sys
import json
import datetime
import time
import pickle
import shutil
import inspect
import importlib
import logging
import threading
from typing import Any, Generator
from collections.abc import Callable
from flask import Flask, Blueprint, make_response, request, render_template, redirect
from flask_socketio import SocketIO
from jinja2 import ChoiceLoader, FileSystemLoader

# pyinstaller
import engineio.async_drivers.threading

sys.modules["init"] = sys.modules[__name__]

DEVMODE = bool(os.environ.get("DEV", False))
logging.basicConfig(level=logging.DEBUG if DEVMODE else logging.INFO)
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

if os.path.exists(old_data_path) and not os.path.exists(data_path):
    os.makedirs(config_dir, exist_ok=True)
    shutil.move(old_data_path, data_path)

app = Flask(__name__, static_folder="static", template_folder="pages")
socket = SocketIO(app, async_mode="threading")
os.chdir(os.path.dirname(os.path.abspath(__file__)))  # sanity check

# Let apps load templates from their own directories
base_dir = os.path.dirname(os.path.abspath(__file__))
# Apps are imported by their top-level ``apps.*`` names, so expose the package
# directory as an import root both in source checkouts and installed wheels.
sys.path.insert(0, base_dir)

app.jinja_env.loader = ChoiceLoader(
    [
        FileSystemLoader(os.path.join(base_dir, "pages").replace("\\", "/")),
        FileSystemLoader(os.path.join(base_dir, "apps").replace("\\", "/")),
        FileSystemLoader(os.path.join(base_dir, "customapps").replace("\\", "/")),
    ]
)

# Only show request logs in debug mode
if not logger.isEnabledFor(logging.DEBUG):
    log = logging.getLogger("werkzeug")
    log.setLevel(logging.WARNING)


def save_config():
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

# App stuff


## Settings
class Setting:
    """
    A setting is a configuration option for an app. Do not call this directly.
    """

    def __init__(
        self, id: str, display_name: str, default: Any, type: str, hidden: bool = False
    ):
        self.id = id
        self.display_name = display_name
        self.default = default
        self.hidden = hidden
        self.type = type
        self.app: App | None = None

    def get_value(self):
        if self.app is None:
            raise ValueError("Setting must be added to an app")
        return config[self.app.id][self.id]

    def set_value(self, value: Any, persist: bool = True):
        if self.app is None:
            raise ValueError("Setting must be added to an app before setting a value")
        config[self.app.id][self.id] = value
        if persist:
            save_config()


class StringSetting(Setting):
    def __init__(self, id: str, display_name: str, default: str, hidden: bool = False):
        super().__init__(id, display_name, default, "string", hidden)


class BooleanSetting(Setting):
    def __init__(self, id: str, display_name: str, default: bool, hidden: bool = False):
        super().__init__(id, display_name, default, "bool", hidden)


class FloatSetting(Setting):
    def __init__(
        self, id: str, display_name: str, default: float, hidden: bool = False
    ):
        super().__init__(id, display_name, default, "float", hidden)


class IntegerSetting(Setting):
    def __init__(self, id: str, display_name: str, default: int, hidden: bool = False):
        super().__init__(id, display_name, default, "int", hidden)


class SelectSetting(Setting):
    def __init__(
        self,
        id: str,
        display_name: str,
        default: str,
        options: dict[str, str],
        hidden: bool = False,
    ):
        super().__init__(id, display_name, default, "select", hidden)
        self.options = options


class DataSetting(Setting):
    def __init__(self, id: str, default: Any):
        super().__init__(id, "", default, "data", True)


class ElementSetting:
    def __init__(self, id: str, type: str, hidden: bool = False):
        self.type = type
        self.id = id
        self.hidden = hidden

    def get_value(self):
        raise NotImplementedError(
            "ElementSettings cannot store data, but get_value was called."
        )

    def set_value(self, value: Any):
        raise NotImplementedError(
            "ElementSettings cannot store data, but set_value was called."
        )


class LinkSetting(ElementSetting):
    def __init__(self, id: str, label: str, link: str, hidden: bool = False):
        super().__init__(id, "link", hidden)
        self.label = label
        self.link = link


class LabelSetting(ElementSetting):
    def __init__(self, id: str, label: str, hidden: bool = False):
        super().__init__(id, "label", hidden)
        self.label = label


## Apps

broadcast_listeners: dict[str, list[Callable]] = {}
READABLE_CATEGORIES = {
    "core": "Core",
    "musicprovider": "Music Providers",
    "device": "Devices",
    "music": "Music",
    "system": "System",
    "uncategorized": "Uncategorized",
}


class App:
    # TODO: docstring these functions to make it easier to build apps
    """
    Represents a pything app, use this class to create your app, and specify settings
    """

    def __init__(
        self,
        settings: list[Setting | ElementSetting],
    ):
        global apps
        stack = inspect.stack()
        self.dir = os.path.dirname(os.path.abspath(stack[1].filename))
        self.dirname = os.path.basename(self.dir)
        atype = os.path.basename(os.path.dirname(self.dir))
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
        apps[self.id] = self
        self.logger = logging.getLogger("pything.app." + self.id)
        logger.debug(f"Initializing app '{self.display_name}' with id '{self.id}'")
        self.blueprint = Blueprint(
            self.id, __name__, static_folder=os.path.abspath(self.dir) + "/static"
        )

        @self.blueprint.context_processor
        def inject_app():
            return {"app": self}

        if not os.path.isdir(atype + os.sep + self.id):
            raise RuntimeError(
                f"Failed to find app directory for '{self.display_name}'"
            )  # sanity check
        self.settings = {s.id: s for s in settings}
        self.hidden = True  # updated on init
        self.listeners = {}
        self.startup_listeners: list[Callable] = []
        self.settingupdatelisteners: list[Callable] = []
        if not self.id in config:
            config[self.id] = {}
        schange = False
        for setting in settings:
            if not isinstance(setting, Setting):
                if isinstance(setting, ElementSetting):
                    continue
                raise ValueError(
                    "Settings must be instances of the Setting or ElementSetting class"
                )
            setting.app = self
            if not setting.id in config[self.id]:
                schange = True
                logger.debug(
                    f"Setting {setting.id} for {self.id} to default of {str(setting.default)}"
                )
                config[self.id][setting.id] = setting.default
        if schange:
            logger.debug("Saving config with new default settings")
            save_config()

    def should_poll(self) -> bool:
        """
        Checks if at least one client has the App open
        """
        for client in clients.values():
            if client.app == self.id:
                return True
        return False

    def get_open_clients(self) -> Generator:
        for client in clients.values():
            if client.app == self.id:
                yield client

    def on(self, event: str):
        def decorator(func):
            self.listeners[event] = func
            return func

        return decorator

    def send(self, event: str, data, to: set[str] | str | None = None):
        logger.debug("serverapp>clientapp: %s > %s", self.id, event)
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
            listener()

    def on_broadcast(self, event: str):
        def decorator(func):
            if event not in broadcast_listeners:
                broadcast_listeners[event] = []
            broadcast_listeners[event].append(func)
            return func

        return decorator

    def broadcast(self, event: str, *args, **kwargs):
        if event not in broadcast_listeners:
            logger.debug(
                "A broadcast to %s was sent by %s, but that event has no listeners",
                event,
                self.id,
            )
            return
        for listener in broadcast_listeners[event]:
            listener(*args, **kwargs)

    def on_setting_update(self, func: Callable):
        self.settingupdatelisteners.append(func)
        return func


apps: dict[str, App] = {}


def get_apps():
    return apps


# Client tracking
class Client:
    def __init__(self, sid) -> None:
        self.sid = sid
        self.app = "dashboard"
        clients[sid] = self

    def change_app(self, app: App | str):
        if isinstance(app, App):
            app = app.id
        if not isinstance(app, str):
            raise ValueError("Argument app must be a string with the ID of the app")
        self.app = app
        socket.emit("changeframe", "/apps/" + app + "/launch", to=self.sid)


clients: dict[str, Client] = {}

# Utilities

client_mods: list[tuple[str, App]] = []
app_mods: list[tuple[str, App]] = []


@app.context_processor
def app_ctx():
    return {"apps": apps, "app_mods": app_mods}


# Built in routes


@app.route("/isready")
def ct_isready():
    res = make_response("OK")
    res.headers["Access-Control-Allow-Origin"] = "*"
    return res


@app.route("/")
def client_redirect():
    return redirect("/client")


@app.route("/client")
def main_client():
    return render_template("client.html", mods=client_mods)


@app.route("/settings")
def settings_editor():
    # sort and hide apps with no visible settings, beware of ai slop
    sapps: dict[str, list[App]] = {}
    for app in apps.values():
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
        readable_categories=READABLE_CATEGORIES,
        custom_hue=config.get("customizer", {}).get("hue", 151),
    )


def app_manifest(app_dir: str) -> dict[str, Any]:
    with open(
        os.path.join(app_dir, "manifest.json"), encoding="utf-8"
    ) as manifest_file:
        manifest = json.load(manifest_file)
    if not isinstance(manifest, dict):
        raise RuntimeError(f"Manifest for app directory '{app_dir}' must be an object")
    dependencies = manifest.get("dependencies", {})
    if not isinstance(dependencies, dict):
        raise RuntimeError(
            f"Manifest for app directory '{app_dir}' has invalid dependencies"
        )
    for dependency_type in ("required", "optional"):
        values = dependencies.setdefault(dependency_type, [])
        if not isinstance(values, list) or not all(
            isinstance(value, str) for value in values
        ):
            raise RuntimeError(
                f"Manifest for app directory '{app_dir}' has invalid {dependency_type} dependencies"
            )
    manifest["dependencies"] = dependencies
    return manifest


def discover_apps() -> dict[str, dict[str, Any]]:
    discovered: dict[str, dict[str, Any]] = {}
    for app_root in ("apps", "customapps"):
        if not os.path.isdir(app_root):
            continue
        for app_name in sorted(os.listdir(app_root)):
            app_dir = os.path.join(app_root, app_name)
            if not os.path.isdir(app_dir) or not os.path.isfile(
                os.path.join(app_dir, "manifest.json")
            ):
                continue
            manifest = app_manifest(app_dir)
            app_id = manifest.get("id")
            if not isinstance(app_id, str):
                raise RuntimeError(
                    f"Manifest for app directory '{app_dir}' has invalid id"
                )
            if app_id in discovered:
                raise RuntimeError(f"App id '{app_id}' is defined more than once")
            discovered[app_id] = {
                "id": app_id,
                "name": manifest.get("name", app_id),
                "description": manifest.get("description", ""),
                "core": manifest.get("core", False),
                "default": manifest.get("default", False),
                "category": manifest.get("category", "uncategorized"),
                "dependencies": manifest["dependencies"],
                "directory": app_dir,
            }
    return discovered


def required_dependency_closure(
    selected: set[str], manifests: dict[str, dict[str, Any]]
) -> set[str]:
    enabled = selected & set(manifests)
    changed = True
    while changed:
        changed = False
        for app_id in tuple(enabled):
            for dependency in manifests[app_id]["dependencies"]["required"]:
                if dependency not in manifests:
                    enabled.remove(app_id)
                    changed = True
                    break
                if dependency not in enabled:
                    enabled.add(dependency)
                    changed = True
    return enabled


def enabled_apps(manifests: dict[str, dict[str, Any]]) -> set[str]:
    # Apply manifest defaults on first start and only to newly discovered apps later.
    default_apps = {
        app_id
        for app_id, manifest in manifests.items()
        if manifest.get("default") is True or manifest["core"]
    }

    # Save the initial selection and installed IDs for future update checks.
    if APP_CONFIG_ID not in config:
        initially_enabled = required_dependency_closure(default_apps, manifests)
        config[APP_CONFIG_ID] = {
            "disabled": sorted(set(manifests) - initially_enabled),
            "known": sorted(manifests),
        }
        save_config()
    else:
        app_config = config[APP_CONFIG_ID]
        if "known" not in app_config:
            # Preserve existing choices when upgrading from configs created before
            # app IDs were tracked.
            app_config["known"] = sorted(manifests)
            save_config()
        else:
            known_apps = set(app_config["known"])
            # Apply defaults only to apps added since the last saved selection.
            new_apps = set(manifests) - known_apps
            if new_apps:
                disabled = set(app_config.get("disabled", []))
                disabled.update(new_apps - default_apps)
                disabled.difference_update(new_apps & default_apps)
                app_config["disabled"] = sorted(disabled)
            if known_apps != set(manifests):
                app_config["known"] = sorted(manifests)
                save_config()

    disabled = set(config.get(APP_CONFIG_ID, {}).get("disabled", []))
    core_apps = {app_id for app_id, manifest in manifests.items() if manifest["core"]}
    return required_dependency_closure(set(manifests) - disabled | core_apps, manifests)


def app_dependency_view(manifests: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    enabled = enabled_apps(manifests)
    app_names = {app_id: manifest["name"] for app_id, manifest in manifests.items()}
    required_by: dict[str, set[str]] = {app_id: set() for app_id in manifests}
    for app_id, manifest in manifests.items():
        for dependency in manifest["dependencies"]["required"]:
            if dependency in required_by and app_id in enabled:
                required_by[dependency].add(app_id)
    result = []
    for app_id in sorted(
        manifests,
        key=lambda item: (manifests[item]["core"], manifests[item]["name"].casefold()),
    ):
        manifest = manifests[app_id]
        missing_required = [
            dependency
            for dependency in manifest["dependencies"]["required"]
            if dependency not in manifests
        ]
        result.append(
            {
                **manifest,
                "enabled": app_id in enabled,
                "required_names": [
                    app_names.get(dependency, dependency)
                    for dependency in manifest["dependencies"]["required"]
                ],
                "optional_names": [
                    app_names.get(dependency, dependency)
                    for dependency in manifest["dependencies"]["optional"]
                ],
                "required_by_names": [
                    app_names.get(dependency, dependency)
                    for dependency in sorted(required_by[app_id])
                ],
                "missing_required": missing_required,
                "missing_required_names": [
                    app_names.get(dependency, dependency)
                    for dependency in missing_required
                ],
            }
        )
    return result


@app.route("/apps", methods=["GET"])
def apps_editor():
    manifests = discover_apps()
    return render_template(
        "apps.html",
        installed_apps=app_dependency_view(manifests),
        custom_hue=config.get("customizer", {}).get("hue", 151),
    )


@app.route("/apps", methods=["POST"])
def apps_set():
    manifests = discover_apps()
    selected = {app_id for app_id in manifests if f"app-{app_id}" in request.form}
    selected.update(
        app_id for app_id, manifest in manifests.items() if manifest["core"]
    )
    enabled = required_dependency_closure(selected, manifests)
    config[APP_CONFIG_ID] = {"disabled": sorted(set(manifests) - enabled)}
    save_config()

    def restart() -> None:
        os._exit(RESTART_EXIT_CODE)

    threading.Timer(0.5, restart).start()
    return (
        "<style>html { background: linear-gradient(350deg, #272727, #1f1f1f); color:"
        " #fff; }</style><h1>PYThing is restarting...</h1><script>const params = new"
        " URLSearchParams(window.location.search); if (!params.has('from')) {"
        " setInterval(() => { fetch('/apps').then(response =>"
        " response.text()).then(data => { window.location.href = '/settings'; }); },"
        " 1000); }</script>"
    )


@app.route("/settings", methods=["POST"])
def settings_set():
    logger.debug("Got new settings: %s", request.form)
    settings_changed = False
    for app in apps.values():
        changed: dict[str, Any] = {}
        for setting in app.settings.values():
            if f"{app.id}-{setting.id}" in request.form:
                nd = request.form[f"{app.id}-{setting.id}"]
                logger.debug(f"Setting '{app.id}' > '{setting.id}' to {str(nd)}")
                match setting.type:
                    case "bool":
                        nd = nd == "on"
                    case "int":
                        nd = int(nd)
                    case "float":
                        nd = float(nd)
                    case "select":
                        if nd not in setting.options:
                            raise ValueError(
                                f"Invalid value for select setting '{setting.id}'"
                            )
                logger.debug(f"Setting as {nd}")
                if setting.get_value() != nd:
                    changed[setting.id] = nd
                    setting.set_value(nd, persist=False)
                    settings_changed = True
        if changed:
            for sl in app.settingupdatelisteners:
                sl(changed)
    if settings_changed:
        save_config()
    return redirect("/settings")


# Socket
@socket.on("connect")
def client_connect(*args, **kwargs):  # pylint: disable=unused-argument
    c = Client(request.sid)  # type: ignore
    socket.emit("dt", datetime.datetime.now().isoformat(), to=c.sid)


@socket.on("disconnect")
def client_disconnect():
    del clients[request.sid]  # type: ignore


@socket.on("open_app")
def client_request_open_app(app):
    logger.debug("%s is opening %s", request.sid, app)  # type: ignore
    clients[request.sid].change_app(app)  # type: ignore


@socket.on("app_com")
def app_client_communications(app, event, data):
    if app not in apps:
        logger.error("A client just sent a request to non-existent app '%s'", app)
        return
    if event == "debug":
        logger.debug("Client debug message to %s: %s", app, data)
        return
    if event not in apps[app].listeners:
        logger.warning(
            "A client just sent a message to '%s' with non-existent event '%s'",
            app,
            event,
        )
        return
    apps[app].listeners[event](data)


@socket.on("debug")
def client_print(d):
    logger.debug("Client message: %s", d)


# Background updates
def clock_thread():
    while True:
        socket.emit("dt", datetime.datetime.now().isoformat())
        time.sleep(60)


def import_app(iappd: str):
    if not os.path.isdir(iappd):
        raise RuntimeError(
            "All apps must be directories, name your app as <name>/__init__.py"
        )
    iapp = importlib.import_module(iappd.replace(os.sep, "."))
    if not hasattr(iapp, "app"):
        raise RuntimeError(f"App {iappd} does not have an 'app' variable")
    # isinstance does not work for some reason, so we check for attributes
    if not (
        hasattr(iapp.app, "id")
        and hasattr(iapp.app, "blueprint")
        and hasattr(iapp.app, "display_name")
    ):
        raise RuntimeError(
            f"App {iappd} variable 'app' does not appear to be a valid App instance ({str(type(iapp.app))})"
        )
    # Make sure the blueprint is valid
    if not isinstance(iapp.app.blueprint, Blueprint):
        raise RuntimeError(
            f"App {iappd} variable 'app' has invalid blueprint ({str(type(iapp.app.blueprint))})"
        )
    app.register_blueprint(iapp.app.blueprint, url_prefix="/apps/" + iapp.app.id)
    if os.path.exists(os.path.join(iappd, "clientmod.html")):
        client_mods.append(
            (os.path.join(iapp.app.id, "clientmod.html").replace("\\", "/"), iapp.app)
        )
    if os.path.exists(os.path.join(iappd, "appmod.html")):
        app_mods.append(
            (os.path.join(iapp.app.id, "appmod.html").replace("\\", "/"), iapp.app)
        )
    for rule in app.url_map.iter_rules():
        if rule.rule == "/apps/" + iapp.app.id + "/launch":
            logger.debug("%s has a launch route", iapp.app.id)
            iapp.app.hidden = False
            break


def main() -> None:
    print(f"Starting PYThing as {__name__}...")
    global apps
    logger.debug("Init apps...")

    # Load enabled apps
    manifests = discover_apps()
    for app_id in sorted(enabled_apps(manifests)):
        import_app(manifests[app_id]["directory"])

    # Sort apps dict
    apps = dict(sorted(apps.items()))

    for loaded_app in apps.values():
        loaded_app.startup()

    # Start clock thread
    threading.Thread(target=clock_thread, daemon=True).start()

    # Start the server
    logger.info("Starting on 127.0.0.1:5192")
    socket.run(app, "127.0.0.1", 5192, allow_unsafe_werkzeug=True)
