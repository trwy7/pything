"""Provider for all music related things, an example of an advanced app"""
import colorsys
import threading

from openrgb import OpenRGBClient
from openrgb.utils import OpenRGBDisconnected, RGBColor
from pything.app import App
from pything.settings import IntegerSetting, LabelSetting, StringSetting

app = App(
    [
        LabelSetting("note1", "This app requires the OpenRGB SDK Server to be running on your system. You can download it from <a href=\"https://openrgb.org\" target=\"_blank\">https://openrgb.org</a>. Ensure that the SDK Server is enabled on startup or that OpenRGB is running as a system service."),
        LabelSetting("note2", "RGB brightness will be kept at whatever it is set to in OpenRGB, this app will only change the color of your devices."),
        StringSetting("api", "OpenRGB SDK Server address", "127.0.0.1"),
        IntegerSetting("port", "OpenRGB SDK Server port", 6742, min_value=1, max_value=65535),
        IntegerSetting("saturation", "Saturation", 90, min_value=0, max_value=100, unit="%"),
        IntegerSetting("value", "Lightness", 80, min_value=0, max_value=100, unit="%")
    ],
)
accent = 151
try:
    openrgb = OpenRGBClient(app.settings["api"].get_value(), app.settings["port"].get_value(), name="pything-openrgb")
except Exception as e:  # noqa: BLE001
    app.logger.error("Failed to connect to OpenRGB: %s", e)
    openrgb = None

@app.on_broadcast("customizer")
def on_customizer_broadcast(data: list[int]):
    global accent
    accent = data[0]
    update_color()

def reconnect_openrgb():
    global openrgb
    if openrgb is not None:
        try:
            openrgb.disconnect()
        except OpenRGBDisconnected:
            app.logger.warning("OpenRGB client was already disconnected")
    try:
        openrgb = OpenRGBClient(app.settings["api"].get_value(), app.settings["port"].get_value(), name="pything-openrgb")
    except Exception as e:  # noqa: BLE001
        app.logger.error("Failed to connect to OpenRGB: %s", e)
        openrgb = None

def _update_color(retry=True):
    # Set all devices to the accent hue
    color = RGBColor(*[int(c * 255) for c in colorsys.hsv_to_rgb(accent / 360, app.settings["saturation"].get_value() / 100, app.settings["value"].get_value() / 100)])
    app.logger.debug("Setting accent to accent=%s, color=%s", accent, color)
    if openrgb is None:
        if retry:
            app.logger.info("Attempting to reconnect to OpenRGB")
            reconnect_openrgb()
            _update_color(retry=False)
        else:
            app.logger.error("Could not reconnect to OpenRGB")
        return
    try:
        for device in openrgb.devices:
            app.logger.debug("Setting device %s to color %s", device.name, color)
            device.set_color(color)
    except OpenRGBDisconnected:
        app.logger.warning("Attempting to reconnect to OpenRGB")
        if retry:
            reconnect_openrgb()
            _update_color(retry=False)
    app.logger.debug("Set all devices to accent hue %s", accent)

def update_color():
    threading.Thread(target=_update_color, daemon=True).start()

@app.on_setting_update
def on_setting_update(changed: dict[str, object]):
    global openrgb
    if "api" in changed or "port" in changed:
        app.logger.info("Restarting OpenRGB client due to API/port change")
        if openrgb:
            try:
                openrgb.disconnect()
            except OpenRGBDisconnected:
                app.logger.warning("OpenRGB client was already disconnected")
        try:
            openrgb = OpenRGBClient(app.settings["api"].get_value(), app.settings["port"].get_value(), name="pything-openrgb")
        except Exception as e:  # noqa: BLE001
            app.logger.error("Failed to connect to OpenRGB Server: %s", e)
            openrgb = None
    update_color()
