from init import App, IntegerSetting, socket

app = App("Customizer", [
    IntegerSetting("color", "UI color (hue)", 151)
])

@app.on_setting_update
def send_customizations():
    socket.emit("customizer", [
        app.settings['color'].get_value() # type: ignore
    ])