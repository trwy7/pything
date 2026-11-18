import os
import sys
import threading
import webbrowser

if sys.platform.startswith("linux"):
    os.environ["PYSTRAY_BACKEND"] = "appindicator"

import darkdetect
import pystray
from PIL import Image

from pything.app import App, stop_server
from pything.state import RESTART_EXIT_CODE, log_file

app = App([])
_HERE = os.path.dirname(__file__)


def _load_icon(filename: str) -> Image.Image:
    """Load an icon and fit it onto a transparent square canvas."""
    icon = Image.open(os.path.join(_HERE, filename)).convert("RGBA")
    size = max(icon.size)
    fitted = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    fitted.paste(icon, ((size - icon.width) // 2, (size - icon.height) // 2), icon)
    return fitted


def _is_system_dark() -> bool:
    """Check if the system tray/taskbar area is using dark mode."""
    if sys.platform.startswith("win"):
        try:
            import winreg  # jank to detect dark mode on windows, since darkdetect only tracks AppsUseLightTheme, not SystemUsesLightTheme

            # ai area, I don't understand the registry enough
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            ) as key:
                val, _ = winreg.QueryValueEx(key, "SystemUsesLightTheme")
                return val == 0
        except OSError:
            pass
    return bool(darkdetect.isDark())


_icons = {
    "light": _load_icon("icon-light.png"),
    "dark": _load_icon("icon-dark.png"),
}

_started_tray = False
_tray_icon: pystray.Icon | None = None
_items: list[pystray.MenuItem] = []


def _on_show_logs(icon, item):
    if log_file is not None:
        webbrowser.open(log_file)


def _on_restart(icon, item):
    icon.stop()
    stop_server(exit_code=RESTART_EXIT_CODE)


def _on_quit(icon, item):
    icon.stop()
    stop_server()


_items = [
    pystray.MenuItem("Show logs", _on_show_logs),
    pystray.MenuItem("Restart", _on_restart),
    pystray.MenuItem("Quit", _on_quit),
]


def add_tray_option(option: str, func):
    app.logger.debug(f"Adding tray option: {option}")
    if _started_tray:
        raise RuntimeError("Cannot add tray options after the tray has started")
    _items.insert(0, pystray.MenuItem(option, func))


def _on_theme_change(theme: str):
    if _tray_icon is not None:
        # On Windows, re-check SystemUsesLightTheme because darkdetect tracks AppsUseLightTheme
        is_dark = (
            _is_system_dark() if sys.platform.startswith("win") else (theme == "Dark")
        )
        _tray_icon.icon = _icons["dark" if is_dark else "light"]


@app.on_startup
def start_tray():
    global _started_tray, _tray_icon
    _started_tray = True

    initial_mode = "dark" if _is_system_dark() else "light"
    _tray_icon = pystray.Icon(
        "pything", _icons[initial_mode], "PYThing", pystray.Menu(*_items)
    )

    # Safer cross-platform alternative to threading.Thread(target=tray_icon.run)
    _tray_icon.run_detached()

    # Event-driven on macOS/Windows (no polling); falls back to polling on Linux
    threading.Thread(
        target=darkdetect.listener, args=(_on_theme_change,), daemon=True
    ).start()
