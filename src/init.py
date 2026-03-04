import os
import sys
import datetime
import time
import pickle
import inspect
import importlib
import logging
import threading
from typing import Any, Generator
from collections.abc import Callable
from flask import Flask, Blueprint, make_response, request, render_template, redirect
from flask_socketio import SocketIO
from jinja2 import ChoiceLoader, FileSystemLoader
import pyinstallerdeps

print(f"Starting PYThing as {__name__}...")
sys.modules['init'] = sys.modules[__name__]

DEVMODE = bool(os.environ.get("DEV", False))
logging.basicConfig(level=logging.DEBUG if DEVMODE else logging.INFO)
logger = logging.getLogger("pything")
if os.name == 'nt':
    data_path = os.path.join(os.environ['APPDATA'], "pything.pkl")
else:
    data_path = os.path.join(os.path.expanduser("~"), ".config", "pything.pkl")

app = Flask(__name__, static_folder="static", template_folder="pages")
socket = SocketIO(app, async_mode='threading')
os.chdir(os.path.dirname(os.path.abspath(__file__))) # sanity check

# Let apps load templates from their own directories
base_dir = os.path.dirname(os.path.abspath(__file__))

app.jinja_env.loader = ChoiceLoader([
    FileSystemLoader(os.path.join(base_dir, "pages").replace('\\', '/')),
    FileSystemLoader(os.path.join(base_dir, "apps").replace('\\', '/')),
    FileSystemLoader(os.path.join(base_dir, "customapps").replace('\\', '/')),
])

# Only show request logs in debug mode
if not logger.isEnabledFor(logging.DEBUG):
    log = logging.getLogger("werkzeug")
    log.setLevel(logging.WARNING)

def save_config():
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
    def __init__(self, id: str, display_name: str, default: Any, type: str, hidden: bool=False):
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
    def set_value(self, value: Any):
        if self.app is None:
            raise ValueError("Setting must be added to an app before setting a value")
        config[self.app.id][self.id] = value
        save_config()

class StringSetting(Setting):
    def __init__(self, id: str, display_name: str, default: str, hidden: bool=False):
        super().__init__(id, display_name, default, "string", hidden)

class BooleanSetting(Setting):
    def __init__(self, id: str, display_name: str, default: bool, hidden: bool=False):
        super().__init__(id, display_name, default, "bool", hidden)

class FloatSetting(Setting):
    def __init__(self, id: str, display_name: str, default: float, hidden: bool=False):
        super().__init__(id, display_name, default, "float", hidden)

class IntegerSetting(Setting):
    def __init__(self, id: str, display_name: str, default: int, hidden: bool=False):
        super().__init__(id, display_name, default, "int", hidden)

class DataSetting(Setting):
    def __init__(self, id: str, default: Any):
        super().__init__(id, "", default, "data", True)

class ElementSetting:
    def __init__(self, id: str, type: str, hidden: bool=False):
        self.type = type
        self.id = id
        self.hidden = hidden
    def get_value(self):
        raise NotImplementedError("ElementSettings cannot store data, but get_value was called.")
    def set_value(self, value: Any):
        raise NotImplementedError("ElementSettings cannot store data, but set_value was called.")

class LinkSetting(ElementSetting):
    def __init__(self, id: str, label: str, link: str, hidden: bool=False):
        super().__init__(id, "link", hidden)
        self.label = label
        self.link = link

class LabelSetting(ElementSetting):
    def __init__(self, id: str, label: str, hidden: bool=False):
        super().__init__(id, "label", hidden)
        self.label = label

## Apps

broadcast_listeners: dict[str, list[Callable]] = {}

class App:
    # TODO: docstring these functions to make it easier to build apps
    """
    Represents a pything app, use this class to create your app, and specify settings
    """
    def __init__(self, display_name: str, settings: list[Setting | ElementSetting], aid: str | None=None):
        global apps
        stack = inspect.stack()
        self.dir = os.path.dirname(os.path.abspath(stack[1].filename))
        self.dirname = os.path.basename(self.dir)
        atype = os.path.basename(os.path.dirname(self.dir))
        if aid is None:
            aname = os.path.basename(self.dir)
            aid = aname
        self.id = aid
        apps[self.id] = self
        self.logger = logging.getLogger("pything.app." + self.id)
        logger.debug(f"Initializing app '{display_name}' with id '{aid}'")
        self.blueprint = Blueprint(self.id, __name__, static_folder=os.path.abspath(self.dir) + "/static")
        @self.blueprint.context_processor
        def inject_app():
            return {"app": self}
        if not os.path.isdir(atype + os.sep + aid):
            raise RuntimeError(f"Failed to find app directory for '{display_name}'") # sanity check
        self.display_name = display_name
        self.settings = {s.id: s for s in settings}
        self.hidden = True # updated on init
        self.listeners = {}
        self.settingupdatelisteners: list[Callable] = []
        if not aid in config:
            config[aid] = {}
        schange = False
        for setting in settings:
            if not isinstance(setting, Setting):
                if isinstance(setting, ElementSetting):
                    continue
                raise ValueError("Settings must be instances of the Setting or ElementSetting class")
            setting.app = self
            if not setting.id in config[aid]:
                schange = True
                logger.debug(f"Setting {setting.id} for {aid} to default of {str(setting.default)}")
                config[aid][setting.id] = setting.default
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
    def send(self, event: str, data, to: list[str] | None=None):
        logger.debug("serverapp>clientapp: %s > %s", self.id, event)
        if isinstance(to, list):
            for c in self.get_open_clients():
                if c.sid in to:
                    socket.emit("app_com", [self.id, event, data], to=c.sid)
        for c in self.get_open_clients():
            socket.emit("app_com", [self.id, event, data], to=c.sid)
    def on_broadcast(self, event: str):
        def decorator(func):
            if event not in broadcast_listeners:
                broadcast_listeners[event] = []
            broadcast_listeners[event].append(func)
            return func
        return decorator
    def broadcast(self, event: str, *args, **kwargs):
        if event not in broadcast_listeners:
            logger.debug("A broadcast to %s was sent by %s, but that event has no listeners", event, self.id)
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
    return {'apps': apps, 'app_mods': app_mods}

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
    return render_template("settings.html")

@app.route("/settings", methods=['POST'])
def settings_set():
    logger.debug("Got new settings: %s", request.form)
    for app in apps.values():
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
                logger.debug(f"Setting as {nd}")
                setting.set_value(nd)
        for sl in app.settingupdatelisteners:
            sl()
    return redirect("/settings")

# Socket
@socket.on("connect")
def client_connect(*args, **kwargs): #pylint: disable=unused-argument
    c = Client(request.sid) # type: ignore
    socket.emit("dt", datetime.datetime.now().isoformat(), to=c.sid)
    socket.sleep(1)
    socket.emit("dt", datetime.datetime.now().isoformat(), to=c.sid)

@socket.on("disconnect")
def client_disconnect():
    del clients[request.sid] # type: ignore

@socket.on("open_app")
def client_request_open_app(app):
    logger.debug("%s is opening %s", request.sid, app) # type: ignore
    clients[request.sid].change_app(app) # type: ignore

@socket.on("app_com")
def app_client_communications(app, event, data):
    if app not in apps:
        logger.error("A client just sent a request to non-existent app '%s'", app)
        return
    if event not in apps[app].listeners:
        logger.warning("A client just sent a message to '%s' with non-existent event '%s'", app, event)
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
        raise RuntimeError("All apps must be directories, name your app as <name>/__init__.py")
    iapp = importlib.import_module(iappd.replace(os.sep, "."))
    if not hasattr(iapp, "app"):
        raise RuntimeError(f"App {iappd} does not have an 'app' variable")
    # isinstance does not work for some reason, so we check for attributes
    if not (hasattr(iapp.app, "id") and hasattr(iapp.app, "blueprint") and hasattr(iapp.app, "display_name")):
        raise RuntimeError(f"App {iappd} variable 'app' does not appear to be a valid App instance ({str(type(iapp.app))})")
    # Make sure the blueprint is valid
    if not isinstance(iapp.app.blueprint, Blueprint):
        raise RuntimeError(f"App {iappd} variable 'app' has invalid blueprint ({str(type(iapp.app.blueprint))})")
    app.register_blueprint(iapp.app.blueprint, url_prefix="/apps/" + iapp.app.id)
    if os.path.exists(os.path.join(iappd, "clientmod.html")):
        client_mods.append((os.path.join(iapp.app.id, "clientmod.html").replace('\\', '/'), iapp.app))
    if os.path.exists(os.path.join(iappd, "appmod.html")):
        app_mods.append((os.path.join(iapp.app.id, "appmod.html").replace('\\', '/'), iapp.app))
    for rule in app.url_map.iter_rules():
        if rule.rule == "/apps/" + iapp.app.id + "/launch":
            logger.debug("%s has a launch route", iapp.app.id)
            iapp.app.hidden = False
            break

if __name__ == "__main__":

    logger.debug("Init apps...")

    # Load apps
    for modapp in os.listdir("apps"):
        import_app(os.path.join("apps", modapp))

    # Load custom apps
    if os.path.isdir("customapps"):
        for modapp in os.listdir("customapps"):
            if os.path.isdir(os.path.join("apps", modapp)):
                raise RuntimeError(f"Custom app '{modapp}' is attempting to overwrite a built in app. Please rename your app directory to avoid conflicts.")
            import_app(os.path.join("customapps", modapp))

    # Start clock thread
    threading.Thread(target=clock_thread, daemon=True).start()

    # Start the server
    logger.info("Starting on 127.0.0.1:5192")
    socket.run(app, "127.0.0.1", 5192, allow_unsafe_werkzeug=True)