"""Provider for all music related things, an example of an advanced app"""

import threading
import time

from pything.app import App
from pything.settings import BooleanSetting, SelectSetting
from pything.web import render_template
from pything.websocket import socket

from .types import playback

_last_broadcast_accent: object = object()

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
    if changed.get("accent") and app.settings["accent"].get_value():
        send_playback_accent()


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


def send_playback_accent():
    global _last_broadcast_accent
    if not playback.song or not app.settings["accent"].get_value():
        return
    accent = playback.song.album.accent
    if accent != _last_broadcast_accent:
        app.broadcast("set_accent", accent)
        _last_broadcast_accent = accent


def send_playback_state():
    socket.emit(
        "music",
        [
            ((playback.position / playback.song.duration) * 100)
            if (
                playback.song
                and playback.position is not None
                and playback.song.duration > 0
            )
            else None,
            playback.playing,
        ],
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
    send_playback_state()
    send_playback_accent()


def playback_estimation_thread():
    while True:
        time.sleep(1)
        playback.estimate_position()
        if playback.song:
            send_playback_state()


@app.on_startup
def start_playback_estimation_thread():
    threading.Thread(target=playback_estimation_thread, daemon=True).start()


@app.blueprint.route("/launch")
def launch():
    return render_template(f"{app.dirname}/pages/playing.html")
