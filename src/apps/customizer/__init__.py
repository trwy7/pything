from init import App, IntegerSetting, socket

app = App("Customize", [
    IntegerSetting("hue", "App hue", 151),
    IntegerSetting("background", "Background lightness (percent)", 24)
])

@socket.on("customizer+get")
@app.on_setting_update
def send_accent(_=None):
    socket.emit("customizer", [app.settings['hue'].get_value(), app.settings['background'].get_value()]) # type: ignore