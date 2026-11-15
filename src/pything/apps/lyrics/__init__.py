import re
import xml.etree.ElementTree as ET
from threading import Lock

import requests
from apps.music.types import playback

from pything.app import App
from pything.settings import StringSetting, BooleanSetting
from pything.web import render_template, request

app = App(
    [
        StringSetting("base_url", "LRCLIB base URL", "https://lrclib.net"),
        BooleanSetting("lrcred", "Use lrc.red for lyrics", False),
        BooleanSetting("showattribution", "Show attribution for lyrics", True),
    ]
)
USER_AGENT = "PYThing Lyrics (https://github.com/trwy7/pything pything@trey7658.com)"
current_lrc: (
    tuple[str, list[tuple[int, str]]] | tuple[str, list[str]] | tuple[str, str]
) = ("", "")
current_source: str | None = None
attempt_again = False
get_lrc_lock = Lock()
bpre = re.compile(
    r"\[(?P<min>[0-9]{1,2}):(?P<sec>[0-9]{1,2})\.(?P<ms>[0-9]{2,3})\](?P<line>.*)"
)


@app.blueprint.route("/launch")
def launch():
    return render_template(
        f"{app.dirname}/pages/lyrics.html",
        show_attribution=app.settings["showattribution"].get_value(),
    )


def _ttml_time(value: str) -> int:
    """Convert a TTML clock value to milliseconds."""
    value = value.strip()
    if ":" in value:
        parts = value.split(":")
        seconds = float(parts[-1]) + int(parts[-2]) * 60
        if len(parts) == 3:
            seconds += int(parts[0]) * 3600
    else:
        seconds = float(value.removesuffix("s"))
    return round(seconds * 1000)


def _fetch_lrcred(cpbs) -> list[tuple[int, str]] | None:
    """Fetch and parse lrc.red TTML lyrics, returning None if unavailable."""
    headers = {"User-Agent": USER_AGENT}
    isrc = cpbs.isrc
    app.logger.debug(
        "Fetching lrc.red lyrics for '%s' (ISRC: %s)",
        cpbs.title,
        isrc or "not available",
    )
    try:
        if not isrc:
            query = f"{cpbs.title} {cpbs.album.title} {cpbs.artists[0].name}"
            app.logger.debug("Searching lrc.red for ISRC with query '%s'", query)
            search = requests.get(
                "https://lrc.red/search.json",
                params={"q": query},
                headers=headers,
                timeout=10,
            )
            app.logger.debug("lrc.red ISRC search returned HTTP %s", search.status_code)
            if search.status_code != 200:
                return None
            hits = search.json().get("hits", [])
            app.logger.debug("lrc.red ISRC search returned %d hits", len(hits))
            isrc = next((hit.get("isrc") for hit in hits if hit.get("isrc")), None)
        if not isrc:
            app.logger.debug("No ISRC found on lrc.red for '%s'", cpbs.title)
            return None

        app.logger.debug("Fetching lrc.red TTML for ISRC %s", isrc)
        response = requests.get(
            f"https://lrc.red/s/{isrc}.ttml", headers=headers, timeout=10
        )
        app.logger.debug("lrc.red TTML request returned HTTP %s", response.status_code)
        if response.status_code != 200:
            return None
        app.logger.debug(
            "Parsing lrc.red TTML response (%d bytes)", len(response.content)
        )
        root = ET.fromstring(response.content)
        lyrics = []
        paragraphs = 0
        for paragraph in root.iter():
            if paragraph.tag.rsplit("}", 1)[-1] != "p":
                continue
            paragraphs += 1
            start = paragraph.attrib.get("begin")
            text = "".join(paragraph.itertext()).strip()
            if start is not None and text:
                lyrics.append((_ttml_time(start), text))
        app.logger.debug(
            "Parsed %d lyric lines from %d TTML paragraphs for '%s'",
            len(lyrics),
            paragraphs,
            cpbs.title,
        )
        return lyrics or None
    except (requests.RequestException, ValueError, ET.ParseError, TypeError):
        app.logger.warning("Could not fetch or parse lrc.red lyrics", exc_info=True)
        return None


def _send_lyrics(lyrics, source: str | None = None, to=None):
    app.send("lyrics", lyrics, to=to)
    app.send("attribution", source, to=to)


def get_current_lrc() -> list[tuple[int, str]] | list[str] | str:
    cpbs = playback.song  # should avoid race conditions
    if not cpbs:
        return "Nothing is playing right now"
    if not cpbs.artists:
        return "This song has no artists"
    global current_lrc, current_source, attempt_again
    if not attempt_again and current_lrc and cpbs.id == current_lrc[0]:
        app.logger.debug("Using cached lyrics for song '%s'", cpbs.title)
        return current_lrc[1]
    with get_lrc_lock:
        if not attempt_again and current_lrc and cpbs.id == current_lrc[0]:
            app.logger.debug("Using cached lyrics for song '%s'", cpbs.title)
            return current_lrc[1]
        attempt_again = False

        # Prefer lrc.red when enabled, but use LRCLIB whenever it has no usable TTML.
        if app.settings["lrcred"].get_value():
            app.logger.debug("Trying lrc.red for song '%s'", cpbs.title)
            lyr = _fetch_lrcred(cpbs)
            if lyr:
                app.logger.debug("Found lyrics on lrc.red for song '%s'", cpbs.title)
                if playback.song and cpbs.id == playback.song.id:
                    current_lrc = (cpbs.id, lyr)
                    current_source = "lrc.red"
                    _send_lyrics(lyr, current_source)
                return lyr
            app.logger.debug(
                "lrc.red had no usable lyrics for '%s'; falling back to LRCLIB",
                cpbs.title,
            )

        app.logger.debug("Fetching LRCLIB lyrics for '%s'", cpbs.title)
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
        app.logger.debug(
            "LRCLIB request returned HTTP %s for '%s'", req.status_code, cpbs.title
        )
        if req.status_code == 429:
            message = f"Rate limited while getting lyrics for '{cpbs.title}' by '{cpbs.artists[0].name}'"
            app.logger.warning("%s: %s", message, req.status_code)
            if playback.song and cpbs.id == playback.song.id:
                current_lrc = (cpbs.id, message)
                current_source = None
                _send_lyrics(message)
            return message
        if req.status_code == 404:
            message = (
                f"Could not find lyrics for '{cpbs.title}' by '{cpbs.artists[0].name}'"
            )
            app.logger.debug("%s: %s", message, req.status_code)
            if playback.song and cpbs.id == playback.song.id:
                current_lrc = (cpbs.id, message)
                current_source = None
                _send_lyrics(message)
            return message
        if req.status_code != 200:
            message = (
                f"Failed to get lyrics for '{cpbs.title}' by '{cpbs.artists[0].name}'"
            )
            app.logger.warning(
                "Could not get lyrics for '%s' by '%s': %s for %s",
                cpbs.title,
                cpbs.artists[0].name,
                req.status_code,
                req.text,
            )
            if playback.song and cpbs.id == playback.song.id:
                current_lrc = (cpbs.id, message)
                current_source = None
                _send_lyrics(message)
            attempt_again = True
            return message
        app.logger.debug("Parsing LRCLIB response for '%s'", cpbs.title)
        data = req.json()
        if data.get("syncedLyrics"):
            app.logger.debug("Found synced lyrics for song '%s'", cpbs.title)
            lyr = parse_lrc(data["syncedLyrics"].splitlines())
        elif data.get("plainLyrics"):
            app.logger.debug("Found plain lyrics for song '%s'", cpbs.title)
            lyr = data["plainLyrics"].splitlines()
        else:
            lyr = "Song is instrumental"
        if isinstance(lyr, list):
            app.logger.debug(
                "Parsed %d lyric lines from LRCLIB for '%s'", len(lyr), cpbs.title
            )
        if playback.song and cpbs.id == playback.song.id:
            current_lrc = (cpbs.id, lyr)
            current_source = "lrclib.net" if isinstance(lyr, list) else None
            _send_lyrics(lyr, current_source)
        return lyr


@playback.on_update
def on_pb_change():
    if app.should_poll():
        get_current_lrc()
        app.send("music", [playback.position, playback.playing])


@app.on("open")
def send_lrc(_):
    lyrics = get_current_lrc()
    app.send("lyrics", lyrics, to=request.sid)
    app.send(
        "attribution",
        current_source if isinstance(lyrics, list) else None,
        to=request.sid,
    )
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
