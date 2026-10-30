from init import App, IntegerSetting, socket

app = App(
    [
        IntegerSetting("hue", "App hue", 151),
        IntegerSetting("background", "Background lightness (percent)", 24),
    ],
)

temp_accent = app.settings["hue"].get_value()
temp_background = app.settings["background"].get_value()


@socket.on("customizer+get")
def rs_accent(_=None):
    socket.emit("customizer", [temp_accent, app.settings["background"].get_value()])


@app.on_setting_update
def send_accent(changed: dict[str, object]):
    global temp_accent, temp_background
    if "hue" in changed:
        temp_accent = changed["hue"]
    if "background" in changed:
        temp_background = changed["background"]
    socket.emit("customizer", [temp_accent, temp_background])


@app.on_broadcast("set_accent")
def set_accent(hue):
    global temp_accent
    temp_accent = hue if hue else app.settings["hue"].get_value()
    socket.emit("customizer", [temp_accent, app.settings["background"].get_value()])
