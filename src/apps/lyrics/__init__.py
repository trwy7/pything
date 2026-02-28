import os
import re
import time
from threading import Lock
import requests
from flask import render_template, request
from init import App
from apps.music.types import playback

app = App("Lyrics", [])
USER_AGENT = "PYThing Lyrics (https://github.com/trwy7/pything)"
current_lrc: tuple[str, list[tuple[int, str]]] | tuple[str, list[str]] | tuple[str, None] | None = None
get_lrc_lock = Lock()
bpre = re.compile(r"\[(?P<min>[0-9]{1,2}):(?P<sec>[0-9]{1,2}).(?P<ms>[0-9]{1,2})\](?P<line>.*)")

@app.blueprint.route("/launch")
def launch():
    return render_template(f"{app.dirname}/pages/lyrics.html")

def get_current_lrc() -> list[tuple[int, str]] | list[str] | None:
    cpbs = playback.song # should avoid race conditions
    if not cpbs:
        return None
    if not (cpbs.artists and cpbs.album):
        # might be possible to get these through /api/search
        return None
    global current_lrc
    if current_lrc and cpbs.id == current_lrc[0]:
        app.logger.debug("Using cached lyrics")
        return current_lrc[1]
    with get_lrc_lock:
        if current_lrc and cpbs.id == current_lrc[0]:
            app.logger.debug("Using cached lyrics")
            return current_lrc[1]
        req = requests.get(
            "https://lrclib.net/api/get",
            params={
                "track_name": cpbs.title,
                "artist_name": cpbs.artists[0].name,
                "album_name": cpbs.album.title,
                "duration": int(cpbs.duration / 1000)
            }
        )
        if req.status_code != 200:
            app.logger.debug("Could not find lyrics for '%s': %s", cpbs.title, req.status_code)
            if playback.song and cpbs.id == playback.song.id:
                current_lrc = (cpbs.id, None)
                app.send("lyrics", None)
            return None
        data = req.json()
        if data['syncedLyrics']:
            app.logger.debug("Found synced lyrics for song '%s'", cpbs.title)
            lyr = parse_lrc(data['syncedLyrics'].splitlines())
            if playback.song and cpbs.id == playback.song.id:
                current_lrc = (cpbs.id, lyr)
                app.send("lyrics", lyr)
            return lyr
        elif data['plainLyrics']:
            app.logger.debug("Found plain lyrics for song '%s'", cpbs.title)
            lyr = data['plainLyrics'].splitlines()
            if playback.song and cpbs.id == playback.song.id:
                current_lrc = (cpbs.id, lyr)
                app.send("lyrics", lyr)
            return lyr
        if playback.song and cpbs.id == playback.song.id:
            current_lrc = (cpbs.id, None)
            app.send("lyrics", None)
        return None

@playback.on_update
def on_pb_change():
    if app.should_poll():
        get_current_lrc()

@app.on("open")
def send_lrc(_):
    app.send("lyrics", get_current_lrc(), to=request.sid) # type: ignore

def parse_lrc(lrc: list[str]) -> list[tuple[int, str]]:
    nlrc = []
    for line in lrc:
        res = re.fullmatch(bpre, line)
        if res is None:
            app.logger.error("Could not match line: %s", line)
        ms = ((60 * int(res.group("min"))) + int(res.group("sec"))) * 1000 + int(res.group("ms")) * 10
        nlrc.append((ms, res.group("line").strip()))
    return nlrc
