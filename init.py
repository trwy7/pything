# TODO: Sort these imports
import os
import sys
import signal
import subprocess
import time
import pickle
import inspect
import importlib
import logging
import threading
from hashlib import sha256
from typing import Any
import requests
from flask import Flask, Blueprint, make_response, request, render_template, redirect
from flask_socketio import SocketIO
from jinja2 import ChoiceLoader, FileSystemLoader, PackageLoader

devmode = True

logging.basicConfig(level=logging.DEBUG if devmode else logging.INFO)
logger = logging.getLogger("pything")

app = Flask(__name__, static_folder="src/static", template_folder="src/pages")
socket = SocketIO(app)
os.chdir(os.path.dirname(os.path.abspath(__file__))) # sanity check

# Let apps load templates from their own directories
app.jinja_env.loader = ChoiceLoader([
    PackageLoader("src", "pages"),
    FileSystemLoader(os.path.dirname(os.path.abspath(__file__)) + "/apps"),
    FileSystemLoader(os.path.dirname(os.path.abspath(__file__)) + "/customapps"),
])

# Only show request logs in debug mode
if not logger.isEnabledFor(logging.DEBUG):
    log = logging.getLogger("werkzeug")
    log.setLevel(logging.WARNING)

# Save time so we dont check for the superbird webapp directory every check
serial_cache = {}

def save_config():
    with open("config.pkl", "wb") as f:
        pickle.dump(config, f)

if os.path.exists("config.pkl"):
    with open("config.pkl", "rb") as f:
        config = pickle.load(f)
else:
    config = {}

# Determine whether to show command output
show_output = logger.isEnabledFor(logging.DEBUG)

# Car Thing stuff
def is_carthing_serial(serial: str):
    if serial in serial_cache:
        return serial_cache[serial][0]
    check_command = f"adb -s {serial} shell '[ -d /usr/share/qt-superbird-app/webapp/ ] && echo exists'"
    result = os.popen(check_command).read().strip()
    if result == "exists":
        logger.debug(f"Found device {serial}")
        serial_cache[serial] = [True, False]
        return True
    else:
        serial_cache[serial] = [False, False]
        return False

def get_carthings():
    connected_devices = os.popen("adb devices").read().strip().splitlines()[1:]
    things = []
    for device in connected_devices:
        if device.strip():
            serial_num = device.split()[0]
            if is_carthing_serial(serial_num):
                things.append(serial_num)
    return things

inject_proc: subprocess.Popen | None = None

def inject_thread(loop=True):
    global inject_proc
    while True:
        connected = get_carthings()
        # Remove disconnected devices
        for serial in list(serial_cache.keys()):
            if serial not in connected:
                logger.info(f"{serial} disconnected")
                del serial_cache[serial]
        # Initialize newly connected devices
        for serial in connected:
            if serial_cache[serial][1]:
                continue
            #if os.system("./ctsetup.sh " + serial + (" >/dev/null 2>&1" if not show_output else "")) == 0:
            #    serial_cache[serial][1] = True
            #else:
            #    logger.error("Car Thing setup failed.")
            # Wait for the script to finish
            # I dont understand this code, but it outputs as expected and it works
            inject_proc = subprocess.Popen(
                ["./ctsetup.sh", serial, "true" if loop else "false"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                text=True,
            )

            # read merged stdout/stderr line-by-line
            if inject_proc.stdout is not None:
                for line in inject_proc.stdout:
                    logger.debug(f"[{serial}] {line.strip()}")
            inject_proc.wait()
            if inject_proc.returncode == 0:
                logger.info(f"Car Thing {serial} setup successful.")
                serial_cache[serial][1] = True
            elif inject_proc.returncode == -9:
                logger.debug(f"Car Thing {serial} was reused.")
                serial_cache[serial][1] = True
            else:
                logger.error(f"Car Thing {serial} setup failed with return code {inject_proc.returncode}.")
            inject_proc = None
        if loop == False:
            return True
        time.sleep(2)

# App stuff

## Settings
class Setting:
    """
    A setting is a configuration option for an app. Do not call this directly.
    """
    def __init__(self, id: str, display_name: str, description: str, default: Any, hidden: bool=False):
        self.id = id
        self.display_name = display_name
        self.description = description
        self.default = default
        self.hidden = hidden
        self.app: App | None = None
    def get_value(self):
        if self.app is None:
            raise ValueError("Setting must be added to an app")
        return config[self.app.id][self.id]

class StringSetting(Setting):
    def __init__(self, id: str, display_name: str, description: str, default: str, hidden: bool=False):
        super().__init__(id, display_name, description, default, hidden)
    def set_value(self, value: str):
        if self.app is None:
            raise ValueError("Setting must be added to an app before setting a value")
        if not isinstance(value, str):
            raise ValueError("Value must be a string")
        config[self.app.id][self.id] = value
        save_config()

class BooleanSetting(Setting):
    def __init__(self, id: str, display_name: str, description: str, default: bool, hidden: bool=False):
        super().__init__(id, display_name, description, default, hidden)
    def set_value(self, value: bool):
        if self.app is None:
            raise ValueError("Setting must be added to an app before setting a value")
        if not isinstance(value, bool):
            raise ValueError("Value must be a boolean")
        config[self.app.id][self.id] = value
        save_config()

class FloatSetting(Setting):
    def __init__(self, id: str, display_name: str, description: str, default: float, hidden: bool=False):
        super().__init__(id, display_name, description, default, hidden)
    def set_value(self, value: float):
        if self.app is None:
            raise ValueError("Setting must be added to an app before setting a value")
        if isinstance(value, int):
            value = float(value)
        if not isinstance(value, float):
            raise ValueError("Value must be a float")
        config[self.app.id][self.id] = value
        save_config()

class IntegerSetting(Setting):
    def __init__(self, id: str, display_name: str, description: str, default: int, hidden: bool=False):
        super().__init__(id, display_name, description, default, hidden)
    def set_value(self, value: int):
        if self.app is None:
            raise ValueError("Setting must be added to an app before setting a value")
        if isinstance(value, int):
            value = int(value)
        if not isinstance(value, int):
            raise ValueError("Value must be a integer")
        config[self.app.id][self.id] = value
        save_config()

## Apps

class App:
    """
    Represents an app, use this class to create your app
    """
    def __init__(self, display_name: str, settings: list[Setting], aid: str | None=None):
        #aid = "s" # FIXME: somehow find the importing python files directory name, prefix customapps with custom-
        stack = inspect.stack()
        self.dir = os.path.dirname(os.path.abspath(stack[1].filename))
        self.dirname = os.path.basename(self.dir)
        atype = os.path.basename(os.path.dirname(self.dir))
        if aid is None:
            aname = os.path.basename(self.dir)
            if atype == "customapps":
                aid = "custom-" + aname
            else:
                aid = aname
        self.id = aid
        self.logger = logging.getLogger("pything.app." + self.id)
        logger.info(f"Initializing app '{display_name}' with id '{aid}'")
        self.blueprint = Blueprint(self.id, __name__, static_folder=os.path.abspath(stack[1].filename) + "/static")
        @app.context_processor
        def inject_app():
            return {"app": self}
        if not os.path.isdir(atype + "/" + aid):
            raise RuntimeError(f"Failed to find app directory for '{display_name}'") # sanity check
        self.display_name = display_name
        self.settings = settings
        if not aid in config:
            config[aid] = {}
        schange = False
        for setting in settings:
            if not isinstance(setting, Setting):
                raise ValueError("Settings must be instances of the Setting class")
            if type(setting) == Setting:
                raise ValueError("Setting must be a subclass of Setting")
            setting.app = self
            if not setting.id in config[aid]:
                schange = True
                logger.debug(f"Setting {setting.id} for {aid} to default of {str(setting.default)}")
                config[aid][setting.id] = setting.default
        if schange:
            logger.debug("Saving config with new default settings")
            save_config()

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
    if request.args.get("carthing") == "true" and request.args.get("ctcv") == "1":
        global inject_proc
        if inject_proc is not None:
            inject_proc.kill()
    return render_template("client.html")

@app.route("/socket.io.min.js")
def socketio_js_route():
    res = make_response(socketio_js)
    res.headers["Content-Type"] = "application/javascript"
    return res

def import_app(iappd: str):
    if not os.path.isdir(iappd):
        raise RuntimeError("All apps must be directories, name your app as <name>/__init__.py")
    iapp = importlib.import_module(iappd.replace("/", "."))
    if not hasattr(iapp, "app"):
        raise RuntimeError(f"App {iappd} does not have an 'app' variable")
    # isinstance does not work for some reason, so we check for attributes
    if not (hasattr(iapp.app, "id") and hasattr(iapp.app, "blueprint") and hasattr(iapp.app, "display_name")):
        raise RuntimeError(f"App {iappd} variable 'app' does not appear to be a valid App instance ({str(type(iapp.app))})")
    # Make sure the blueprint is valid
    if not isinstance(iapp.app.blueprint, Blueprint):
        raise RuntimeError(f"App {iappd} variable 'app' has invalid blueprint ({str(type(iapp.app.blueprint))})")
    app.register_blueprint(iapp.app.blueprint, url_prefix="/apps/" + iapp.app.id.removeprefix("custom-"))

# Restore carthing webapp
def restore_ct_webapp(sig=None, frame=None):
    for serial in get_carthings():
        if is_carthing_serial(serial):
            logger.info(f"Restoring {serial}...")
            os.system(f"./ctrestore.sh {serial} {'>/dev/null 2>&1' if not show_output else ''}")
    sys.exit(0)

if len(sys.argv) > 1:
    match sys.argv[1]:
        case "inject":
            inject_thread(loop=False)
        case "restore":
            restore_ct_webapp()
        case _:
            print("Invalid command:", sys.argv[1])
            sys.exit(1)
    sys.exit(0)

# Cache the socketIO script. 
socketio_js = requests.get("https://cdn.socket.io/4.8.1/socket.io.min.js").text
# Make sure this socketio version has not been compromised
if sha256(socketio_js.encode("UTF-8")).hexdigest() != "b0e735814f8dcfecd6cdb8a7ce95a297a7e1e5f2727a29e6f5901801d52fa0c5":
    raise RuntimeError("Failed to download the socketio 4.8.1 js file (hash mismatch).")

if __name__ == "__main__":

    # Load apps
    for modapp in os.listdir("apps"):
        import_app(os.path.join("apps", modapp))

    # Load custom apps
    if os.path.isdir("customapps"):
        for modapp in os.listdir("customapps"):
            if os.path.isdir(os.path.join("apps", modapp)):
                raise RuntimeError(f"Custom app '{modapp}' is attempting to overwrite a built in app. Please rename your app directory to avoid conflicts.")
            import_app(os.path.join("customapps", modapp))

    # Push webapp
    if os.environ.get("PYTHING_PUSH_WEBAPP", "true").lower() == "true":
        threading.Thread(target=inject_thread, daemon=True).start()
        if not devmode:
            signal.signal(signal.SIGINT, restore_ct_webapp)
    # Start the server
    socket.run(app, "127.0.0.1", 5192)