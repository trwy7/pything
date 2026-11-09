import configparser
import os
import shutil
import subprocess
import sys
import threading
import time
import webbrowser

if sys.platform.startswith("linux"):
    os.environ["PYSTRAY_BACKEND"] = "appindicator"

import pystray
from PIL import Image

from pything.app import App, stop_server
from pything.state import log_file

app = App([])

_HERE = os.path.dirname(__file__)


def _load_icon(filename: str) -> Image.Image:
    """Load an icon and fit it onto a transparent square canvas."""
    icon = Image.open(os.path.join(_HERE, filename)).convert("RGBA")
    # workaround for non-square image bc im lazy
    size = max(icon.size)
    fitted = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    icon.thumbnail((size, size), Image.Resampling.LANCZOS)
    fitted.paste(icon, ((size - icon.width) // 2, (size - icon.height) // 2), icon)
    return fitted


def _gsettings_get(schema: str, key: str) -> str | None:
    if shutil.which("gsettings") is None:
        return None
    try:
        result = subprocess.run(
            ["gsettings", "get", schema, key],
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _is_dark_mode_linux() -> bool | None:
    # GNOME / freedesktop color-scheme (most reliable on modern desktops)
    color_scheme = _gsettings_get("org.gnome.desktop.interface", "color-scheme")
    if color_scheme is not None:
        if "prefer-dark" in color_scheme:
            return True
        if "prefer-light" in color_scheme:
            return False

    # Legacy GTK theme name, e.g. "Adwaita-dark"
    gtk_theme = _gsettings_get("org.gnome.desktop.interface", "gtk-theme")
    if gtk_theme is not None and "dark" in gtk_theme.lower():
        return True

    if "dark" in os.environ.get("GTK_THEME", "").lower():
        return True

    settings_ini = os.path.expanduser("~/.config/gtk-3.0/settings.ini")
    if os.path.isfile(settings_ini):
        parser = configparser.ConfigParser()
        try:
            parser.read(settings_ini)
            theme_name = parser.get("Settings", "gtk-theme-name", fallback="")
        except configparser.Error:
            theme_name = ""
        if "dark" in theme_name.lower():
            return True

    return None


def _is_dark_mode_windows() -> bool | None:
    try:
        import winreg
    except ImportError:
        return None
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            apps_use_light_theme, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
    except OSError:
        return None
    return apps_use_light_theme == 0


def _is_dark_mode_macos() -> bool | None:
    try:
        result = subprocess.run(
            ["defaults", "read", "-g", "AppleInterfaceStyle"],
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() == "Dark"


def is_dark_mode() -> bool:
    """Return True if the OS is in dark mode, False for light/unknown."""
    if sys.platform.startswith("win"):
        result = _is_dark_mode_windows()
    elif sys.platform == "darwin":
        result = _is_dark_mode_macos()
    elif sys.platform.startswith("linux"):
        result = _is_dark_mode_linux()
    else:
        result = None
    return bool(result)


_icons = {
    "light": _load_icon("icon-light.png"),
    "dark": _load_icon("icon-dark.png"),
}
_current_mode = "dark" if is_dark_mode() else "light"


def after_click(icon, item):
    match str(item):
        case "Show logs":
            if log_file is not None:
                webbrowser.open(log_file)
        case "Quit":
            icon.stop()
            stop_server()


started_tray = False
items = [
    pystray.MenuItem("Show logs", after_click),
    pystray.MenuItem("Quit", after_click),
]


def add_tray_option(option: str, func):
    app.logger.debug(f"Adding tray option: {option}")
    if started_tray:
        raise RuntimeError("Cannot add tray options after the tray has started")
    items.insert(0, pystray.MenuItem(option, func))


def _watch_theme():
    global _current_mode
    while True:
        time.sleep(3)
        mode = "dark" if is_dark_mode() else "light"
        if mode != _current_mode:
            _current_mode = mode
            try:
                tray_icon.icon = _icons[mode]
            except Exception:
                pass


@app.on_startup
def start_tray():
    global started_tray, tray_icon
    started_tray = True
    tray_icon = pystray.Icon(
        "pything", _icons[_current_mode], "PyThing", pystray.Menu(*items)
    )
    threading.Thread(target=tray_icon.run, daemon=True).start()
    threading.Thread(target=_watch_theme, daemon=True).start()
