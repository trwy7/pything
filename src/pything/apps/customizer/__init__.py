from pything import App, IntegerSetting, socket

app = App(
    [
        IntegerSetting("hue", "App hue", 151),
        IntegerSetting("backgroundlighttop", "Background top lightness (percent)", 40),
        IntegerSetting("backgroundsattop", "Background top saturation (percent)", 35),
        IntegerSetting("backgroundlightbottom", "Background bottom lightness (percent)", 57),
        IntegerSetting("backgroundsatbottom", "Background bottom saturation (percent)", 8),
    ],
)

temp_accent = app.settings["hue"].get_value()
temp_background_light_top = app.settings["backgroundlighttop"].get_value()
temp_background_sat_top = app.settings["backgroundsattop"].get_value()
temp_background_light_bottom = app.settings["backgroundlightbottom"].get_value()
temp_background_sat_bottom = app.settings["backgroundsatbottom"].get_value()



@app.on_setting_update
def send_accent(changed: dict[str, object]):
    global temp_accent, temp_background_light_top, temp_background_sat_top, temp_background_light_bottom, temp_background_sat_bottom
    if "hue" in changed:
        temp_accent = changed["hue"]
    if "backgroundlighttop" in changed:
        temp_background_light_top = changed["backgroundlighttop"]
    if "backgroundsattop" in changed:
        temp_background_sat_top = changed["backgroundsattop"]
    if "backgroundlightbottom" in changed:
        temp_background_light_bottom = changed["backgroundlightbottom"]
    if "backgroundsatbottom" in changed:
        temp_background_sat_bottom = changed["backgroundsatbottom"]

    socket.emit("customizer", [temp_accent, temp_background_light_top, temp_background_sat_top, temp_background_light_bottom, temp_background_sat_bottom])


@socket.on("customizer+get")
def rs_accent(_=None):
    send_accent({})

@app.on_broadcast("set_accent")
def set_accent(hue):
    send_accent({"hue": hue})
