from init import App, IntegerSetting, socket

app = App("Customize", [
    IntegerSetting("hue", "App hue", 151),
    IntegerSetting("background", "Background lightness (percent)", 24)
])

temp_accent = app.settings['hue'].get_value() # type: ignore

@socket.on("customizer+get")
def rs_accent(_=None):
    socket.emit("customizer", [temp_accent, app.settings['background'].get_value()]) # type: ignore

@app.on_setting_update
def send_accent():
    global temp_accent
    temp_accent = app.settings['hue'].get_value() # type: ignore
    socket.emit("customizer", [temp_accent, app.settings['background'].get_value()]) # type: ignore

@app.on_broadcast("set_accent")
def set_accent(hue):
    global temp_accent
    temp_accent = hue if hue else app.settings['hue'].get_value() # type: ignore
    socket.emit("customizer", [temp_accent, app.settings['background'].get_value()]) # type: ignore