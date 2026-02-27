import os
from threading import Lock
import requests
from flask import render_template
from init import App
from apps.music.types import playback, Song

app = App("Lyrics", [])
USER_AGENT = "PYThing Lyrics (https://github.com/trwy7/pything)"
current_lrc: tuple[str, list[tuple[int, str] | str]] | None = None
get_lrc_lock = Lock()

@app.blueprint.route("/launch")
def launch():
    return render_template(f"{app.dirname}/pages/lyrics.html")

def get_current_lrc() -> list[tuple[int, str] | str] | None:
    if not playback.song:
        return None
    if not (playback.song.artists and playback.song.album):
        # might be possible to get these through /api/search
        return None
    with get_lrc_lock:
        req = requests.get(
            "https://lrclib.net/api/get",
            params={
                "track_name": playback.song.title,
                "artist_name": playback.song.artists[0].name,
                "album_name": playback.song.album.title,
                "duration": int(playback.song.duration / 1000)
            }
        )
        if req.status_code != 200:
            app.logger.debug("Could not find lyrics for '%s': %s", playback.song.title, req.status_code)
        data = req.json()
        if data['syncedLyrics']:
            app.logger.debug("Found synced lyrics for '%s'", playback.song.title)
        elif data['plainLyrics']:
            app.logger.debug("Found plain lyrics for '%s'", playback.song.title)
        return None

@playback.on_update
def on_pb_change():
    get_current_lrc()

def parse_lrc(lrc: str) -> list[tuple[int, str]]:
    pass
