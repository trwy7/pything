"""Provider for all music related things, an example of an advanced app"""

from flask import render_template
from init import App, socket, BooleanSetting, SelectSetting
from .types import playback

app = App(
    [
        BooleanSetting("accent", "Set accent color to art accent", True),
        SelectSetting(
            "playbar_style",
            "Playbar style",
            "rounded",
            {"rounded": "Rounded", "flat": "Flat", "off": "Off"},
        ),
    ],
)


@app.on_setting_update
def send_playbar_style(changed: dict[str, object]):
    if "playbar_style" in changed:
        socket.emit("music_playbar_style", changed["playbar_style"])


@app.on("get")
@playback.on_update
def send_song(_=None):
    app.send(
        "song",
        {
            "title": playback.song.title,
            "album": playback.song.album.title,
            "artists": ", ".join([a.name for a in playback.song.artists]),
            "art": playback.song.album.art,
        }
        if playback.song
        else None,
    )


@playback.on_update
def playback_listener():
    if playback.song:
        app.logger.debug(
            "Got playback update: id=%s, title=%s, position=%s, playing=%s",
            playback.song.id,
            playback.song.title,
            playback.position,
            playback.playing,
        )
    else:
        app.logger.debug("Got playback update: None")
    socket.emit(
        "music",
        [
            ((playback.position / playback.song.duration) * 100)
            if playback.song and playback.position and playback.song.duration > 0
            else None,
            playback.playing,
        ],
    )
    if playback.song and app.settings["accent"].get_value():
        app.broadcast("set_accent", playback.song.album.accent)


@app.blueprint.route("/launch")
def launch():
    return render_template(f"{app.dirname}/pages/playing.html")
