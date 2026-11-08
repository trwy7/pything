import os
import sys
import threading
import webbrowser

if sys.platform.startswith("linux"):
    os.environ["PYSTRAY_BACKEND"] = "appindicator"

import pystray
from PIL import Image

from pything.app import App, stop_server
from pything.state import log_file

app = App([])
icon = Image.open(os.path.join(os.path.dirname(__file__), "icon.png"))


def after_click(icon, item):
    match str(item):
        case "Show logs":
            if log_file is not None:
                webbrowser.open(log_file)
        case "Quit":
            icon.stop()
            stop_server()


menu = pystray.Menu(
    pystray.MenuItem("Show logs", after_click),
    pystray.MenuItem("Quit", after_click),
)

def add_tray_option(option, func):
    menu.insert(0, pystray.MenuItem(option, func))

icon = pystray.Icon("pything", icon, "PyThing", menu)


@app.on_startup
def start_tray():
    threading.Thread(target=icon.run, daemon=True).start()
