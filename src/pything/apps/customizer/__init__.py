from pything import App, IntegerSetting, socket

app = App(
    [
        IntegerSetting("hue", "App hue", 151, min_value=0, max_value=360, unit="°"),
        IntegerSetting(
            "bgrotation",
            "Background rotation",
            350,
            min_value=0,
            max_value=360,
            unit="°",
        ),
        IntegerSetting(
            "backgroundlighttop",
            "Background top lightness",
            40,
            min_value=0,
            max_value=100,
            unit="%",
        ),
        IntegerSetting(
            "backgroundsattop",
            "Background top saturation",
            35,
            min_value=0,
            max_value=100,
            unit="%",
        ),
        IntegerSetting(
            "backgroundlightbottom",
            "Background bottom lightness",
            57,
            min_value=0,
            max_value=100,
            unit="%",
        ),
        IntegerSetting(
            "backgroundsatbottom",
            "Background bottom saturation",
            8,
            min_value=0,
            max_value=100,
            unit="%",
        ),
    ],
)

temp_accent = app.settings["hue"].get_value()
temp_bgrotation = app.settings["bgrotation"].get_value()
temp_background_light_top = app.settings["backgroundlighttop"].get_value()
temp_background_sat_top = app.settings["backgroundsattop"].get_value()
temp_background_light_bottom = app.settings["backgroundlightbottom"].get_value()
temp_background_sat_bottom = app.settings["backgroundsatbottom"].get_value()


@app.on_setting_update
def send_accent(changed: dict[str, object]):
    global \
        temp_accent, \
        temp_background_light_top, \
        temp_background_sat_top, \
        temp_background_light_bottom, \
        temp_background_sat_bottom, \
        temp_bgrotation
    if "hue" in changed:
        temp_accent = changed["hue"]
    if "bgrotation" in changed:
        temp_bgrotation = changed["bgrotation"]
    if "backgroundlighttop" in changed:
        temp_background_light_top = changed["backgroundlighttop"]
    if "backgroundsattop" in changed:
        temp_background_sat_top = changed["backgroundsattop"]
    if "backgroundlightbottom" in changed:
        temp_background_light_bottom = changed["backgroundlightbottom"]
    if "backgroundsatbottom" in changed:
        temp_background_sat_bottom = changed["backgroundsatbottom"]
    socket.emit(
        "customizer",
        [
            temp_accent,
            temp_bgrotation,
            temp_background_light_top,
            temp_background_sat_top,
            temp_background_light_bottom,
            temp_background_sat_bottom,
        ],
    )
    app.broadcast(
        "customizer",
        [
            temp_accent,
            temp_bgrotation,
            temp_background_light_top,
            temp_background_sat_top,
            temp_background_light_bottom,
            temp_background_sat_bottom,
        ],
    )


@socket.on("customizer+get")
def rs_accent(_=None):
    send_accent({})


@app.on_broadcast("set_accent")
def set_accent(hue):
    send_accent({"hue": hue})
