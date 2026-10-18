import re
from threading import Lock
import requests
from flask import render_template, request
from init import App, StringSetting
from apps.music.types import playback

app = App("Lyrics", [
    StringSetting("base_url", "LRCLIB base URL", "https://lrclib.net")
], category="music")
USER_AGENT = "PYThing Lyrics (https://github.com/trwy7/pything)"
current_lrc: (
    tuple[str, list[tuple[int, str]]] | tuple[str, list[str]] | tuple[str, str]
) = ("", "")
attempt_again = False
get_lrc_lock = Lock()
bpre = re.compile(
    r"\[(?P<min>[0-9]{1,2}):(?P<sec>[0-9]{1,2})\.(?P<ms>[0-9]{2,3})\](?P<line>.*)"
)


@app.blueprint.route("/launch")
def launch():
    return render_template(f"{app.dirname}/pages/lyrics.html")


def get_current_lrc() -> list[tuple[int, str]] | list[str] | str:
    cpbs = playback.song  # should avoid race conditions
    if not cpbs:
        return "Nothing is playing right now"
    if not cpbs.artists:
        # might be possible to get these through /api/search
        return "This song has no artists"
    global current_lrc, attempt_again
    if not attempt_again and current_lrc and cpbs.id == current_lrc[0]:
        app.logger.debug("Using cached lyrics for song '%s'", cpbs.title)
        return current_lrc[1]
    with get_lrc_lock:
        if not attempt_again and current_lrc and cpbs.id == current_lrc[0]:
            app.logger.debug("Using cached lyrics for song '%s'", cpbs.title)
            return current_lrc[1]
        attempt_again = False
        req = requests.get(
            f"{app.settings['base_url'].get_value()}/api/get",
            params={
                "track_name": cpbs.title,
                "artist_name": cpbs.artists[0].name,
                "album_name": cpbs.album.title,
                "duration": int(cpbs.duration / 1000),
            },
            headers={"User-Agent": USER_AGENT},
        )
        if req.status_code == 429:
            app.logger.warning(
                "Rate limited while getting lyrics for '%s' by '%s': %s",
                cpbs.title,
                cpbs.artists[0].name,
                req.status_code,
            )
            if playback.song and cpbs.id == playback.song.id:
                current_lrc = (
                    cpbs.id,
                    f"Rate limited while getting lyrics for '{cpbs.title}' by '{cpbs.artists[0].name}'",
                )
                app.send("lyrics", current_lrc[1])
            return f"Rate limited while getting lyrics for '{cpbs.title}' by '{cpbs.artists[0].name}'"
        if req.status_code == 404:
            app.logger.debug(
                "Could not find lyrics for '%s' by '%s': %s",
                cpbs.title,
                cpbs.artists[0].name,
                req.status_code,
            )
            if playback.song and cpbs.id == playback.song.id:
                current_lrc = (
                    cpbs.id,
                    f"Could not find lyrics for '{cpbs.title}' by '{cpbs.artists[0].name}'",
                )
                app.send("lyrics", current_lrc[1])
            return (
                f"Could not find lyrics for '{cpbs.title}' by '{cpbs.artists[0].name}'"
            )
        if req.status_code != 200:
            app.logger.warning(
                "Could not get lyrics for '%s' by '%s': %s for %s",
                cpbs.title,
                cpbs.artists[0].name,
                req.status_code,
                req.text
            )
            if playback.song and cpbs.id == playback.song.id:
                current_lrc = (
                    cpbs.id,
                    f"Failed to get lyrics for '{cpbs.title}' by '{cpbs.artists[0].name}'",
                )
                app.send("lyrics", current_lrc[1])
            attempt_again = True
            return f"Failed to get lyrics for '{cpbs.title}' by '{cpbs.artists[0].name}'"
        data = req.json()
        if data["syncedLyrics"]:
            app.logger.debug("Found synced lyrics for song '%s'", cpbs.title)
            lyr = parse_lrc(data["syncedLyrics"].splitlines())
            if playback.song and cpbs.id == playback.song.id:
                current_lrc = (cpbs.id, lyr)
                app.send("lyrics", lyr)
            return lyr
        elif data["plainLyrics"]:
            app.logger.debug("Found plain lyrics for song '%s'", cpbs.title)
            lyr = data["plainLyrics"].splitlines()
            if playback.song and cpbs.id == playback.song.id:
                current_lrc = (cpbs.id, lyr)
                app.send("lyrics", lyr)
            return lyr
        if playback.song and cpbs.id == playback.song.id:
            current_lrc = (cpbs.id, "Song is instrumental")
            app.send("lyrics", current_lrc[1])
        return "Song is instrumental"


@playback.on_update
def on_pb_change():
    if app.should_poll():
        get_current_lrc()
        app.send("music", [playback.position, playback.playing])


@app.on("open")
def send_lrc(_):
    app.send("lyrics", get_current_lrc(), to=request.sid)
    app.send("music", [playback.position, playback.playing])


def parse_lrc(lrc: list[str]) -> list[tuple[int, str]]:
    nlrc = []
    for line in lrc:
        if line.strip() == "":
            continue
        res = re.fullmatch(bpre, line.strip())
        if res == None:
            app.logger.warning("Could not match line: %s", line)
            continue
        tms = res.group("ms")
        ms = ((60 * int(res.group("min"))) + int(res.group("sec"))) * 1000 + int(
            tms
        ) * (10 if len(tms) == 2 else 1)
        nlrc.append((ms, res.group("line").strip()))
    return nlrc
