import re
import xml.etree.ElementTree as ET
from threading import Lock

import requests
from _pything_apps.music.types import playback  # TODO: maybe figure out typing

from pything.app import App
from pything.settings import BooleanSetting, StringSetting
from pything.web import render_template, request

app = App(
    [
        StringSetting("base_url", "LRCLIB base URL", "https://lrclib.net"),
        BooleanSetting("lrcred", "Use lrc.red for lyrics", False),
        BooleanSetting("showattribution", "Show attribution for lyrics", True),
    ]
)
USER_AGENT = "PYThingLyrics/1.0 ( https://github.com/trwy7/pything )"
current_lrc: (
    tuple[str, list[tuple[int, str]]]
    | tuple[str, list[str]]
    | tuple[str, list[dict]]
    | tuple[str, str]
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


def _xml_attr(element, name: str) -> str | None:
    return next(
        (
            value
            for key, value in element.attrib.items()
            if key.rsplit("}", 1)[-1] == name
        ),
        None,
    )


def _is_background(element) -> bool:
    return _xml_attr(element, "role") == "x-bg"


def _element_text(element, skip_background: bool = False) -> str:
    parts = [element.text or ""]
    for child in element:
        if not (skip_background and _is_background(child)):
            parts.append(_element_text(child, skip_background))
        parts.append(child.tail or "")
    return "".join(parts).strip()


def _element_times(element) -> tuple[int | None, int | None]:
    starts, ends = [], []
    for node in element.iter():
        begin, end = _xml_attr(node, "begin"), _xml_attr(node, "end")
        try:
            if begin is not None:
                starts.append(_ttml_time(begin))
            if end is not None:
                ends.append(_ttml_time(end))
        except ValueError:
            continue
    return min(starts, default=None), max(ends, default=None)


def _parse_lrcred_ttml(content: bytes) -> list[dict]:
    """Parse timed TTML lines, retaining speaker and concurrent background vocals."""
    root = ET.fromstring(content)
    body = next(
        (node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "body"), root
    )
    body_agent = _xml_attr(body, "agent")
    rows = []

    for div in (node for node in body.iter() if node.tag.rsplit("}", 1)[-1] == "div"):
        if _xml_attr(div, "songPart") == "Instrumental":
            continue
        div_agent = _xml_attr(div, "agent") or body_agent
        for paragraph in (node for node in div if node.tag.rsplit("}", 1)[-1] == "p"):
            line_start, line_end = _element_times(paragraph)
            line_start = (
                _ttml_time(_xml_attr(paragraph, "begin"))
                if _xml_attr(paragraph, "begin")
                else line_start
            )
            line_end = (
                _ttml_time(_xml_attr(paragraph, "end"))
                if _xml_attr(paragraph, "end")
                else line_end
            )
            text = _element_text(paragraph, skip_background=True)
            agent = _xml_attr(paragraph, "agent") or div_agent
            backgrounds = []

            def collect_backgrounds(
                parent,
                backgrounds=backgrounds,  # lint things
                default_start=line_start,  # lint things
                default_end=line_end,  # lint things
            ):
                for child in parent:
                    if _is_background(child):
                        bg_text = _element_text(child)
                        if bg_text:
                            bg_start, bg_end = _element_times(child)
                            backgrounds.append(
                                {
                                    "time": bg_start
                                    if bg_start is not None
                                    else default_start,
                                    "end": bg_end
                                    if bg_end is not None
                                    else default_end,
                                    "text": bg_text,
                                }
                            )
                    else:
                        collect_backgrounds(child)

            collect_backgrounds(paragraph)
            if not text and not backgrounds:
                continue
            if line_start is None:
                line_start = min(
                    (bg["time"] for bg in backgrounds if bg["time"] is not None),
                    default=0,
                )
            rows.append(
                {
                    "time": line_start,
                    "end": line_end,
                    "text": text,
                    "speaker": agent,
                    "opposite": agent in {"v2", "v2000"},
                    "background": backgrounds,
                }
            )

    return sorted(rows, key=lambda row: row["time"])


def _fetch_lrcred(cpbs) -> list[dict] | None:
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
            # Search musicbrainz for the ISRC if not available from the provider
            app.logger.debug("Searching MusicBrainz for ISRC of '%s'", cpbs.title)
            title = re.sub(
                r"\s*(?:\([^)]*\)|\[[^]]*\]|(?:feat\.?|ft\.?|featuring)\s+.*)$",  # very ai regex to hopefully detect patterns that musicbrainz misses
                "",
                cpbs.title,
                flags=re.IGNORECASE,
            ).strip()
            query = [
                f'recording:"{title}"',
                f'release:"{cpbs.album.title}"',
                f'artist:"{cpbs.artists[0].name}"',
                "NOT comment:instrumental",
                "NOT disambiguation:instrumental",
                "NOT secondarytype:karaoke",
                f"dur:[{cpbs.duration - 5000} TO {cpbs.duration + 5000}]",
            ]
            mb_query = " AND ".join(query)
            app.logger.debug("MusicBrainz query: %s", mb_query)
            mb_response = requests.get(
                "https://musicbrainz.org/ws/2/recording",
                params={"query": mb_query, "fmt": "json"},
                headers=headers,
                timeout=10,
            )
            if mb_response.status_code == 200:
                mb_data = mb_response.json()
                for rec in mb_data.get("recordings", []):
                    isrcs = rec.get("isrcs")
                    if isrcs:
                        isrc = isrcs[0]
                        app.logger.debug(
                            "Found ISRC '%s' for '%s' on MusicBrainz",
                            isrc,
                            rec.get("title", "<unknown>"),
                        )
                        break
            else:
                app.logger.warning(
                    "MusicBrainz request failed for '%s': %s %s",
                    cpbs.title,
                    mb_response.status_code,
                    mb_response.text,
                )
        if not isrc:
            app.logger.debug(
                "No ISRC found on musicbrainz for '%s': %s",
                cpbs.title,
                mb_response.text,
            )
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
        lyrics = _parse_lrcred_ttml(response.content)
        app.logger.debug(
            "Parsed %d TTML lyric lines for '%s' (%d with background vocals)",
            len(lyrics),
            cpbs.title,
            sum(bool(line["background"]) for line in lyrics),
        )
        return lyrics or None
    except (requests.RequestException, ValueError, ET.ParseError, TypeError):
        app.logger.warning("Could not fetch or parse lrc.red lyrics", exc_info=True)
        return None


def _send_lyrics(lyrics, source: str | None = None, to=None):
    app.send("lyrics", lyrics, to=to)
    app.send("attribution", source, to=to)


def get_current_lrc() -> list[tuple[int, str]] | list[str] | list[dict] | str:
    global current_lrc, current_source, attempt_again
    cpbs = playback.song  # should avoid race conditions
    if not cpbs:
        app.logger.debug("No song is currently playing; returning empty lyrics")
        return "Nothing is playing right now"
    if not cpbs.artists:
        app.logger.debug("Song '%s' has no artists; skipping lyrics search", cpbs.title)
        message = "This song has no artists"
        if playback.song and cpbs.id == playback.song.id:
            current_lrc = (cpbs.id, message)
            current_source = None
            _send_lyrics(message)
        return message
    if not cpbs.album or not cpbs.album.title:  # assume misc media that isnt a song
        app.logger.debug("Skipping lyrics search for '%s' (no album title)", cpbs.title)
        message = "Skipped search for '" + cpbs.title + "'"
        if playback.song and cpbs.id == playback.song.id:
            current_lrc = (cpbs.id, message)
            current_source = None
            _send_lyrics(message)
        return message
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
        app.logger.debug("Playback changed; sending updated lyrics and music info")
        get_current_lrc()
        app.send("music", [playback.position, playback.playing])


@app.on("open")
def send_lrc(_):
    app.logger.debug("Client connected; sending current lyrics and music info")
    lyrics = get_current_lrc()
    app.send("lyrics", lyrics, to=request.sid)
    app.send(
        "attribution",
        current_source if isinstance(lyrics, list) else None,
        to=request.sid,
    )
    app.send("music", [playback.position, playback.playing])


def parse_lrc(lrc: list[str]) -> list[tuple[int, str]] | list[str]:
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
    if nlrc and all(timestamp == 0 for timestamp, _ in nlrc):
        return [line for _, line in nlrc]
    return nlrc
