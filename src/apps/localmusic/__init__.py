import asyncio
import base64
import binascii
import hashlib
import os
import shutil
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, unquote_to_bytes, urlparse

from flask import abort, send_file

from apps.music.types import Album, Artist, Song, playback
from apps.music.utils import get_accent
from init import App, BooleanSetting, LabelSetting, StringSetting

app = App("Local Music", [
    BooleanSetting("enabled", "Enabled", False, False),
    LabelSetting("providers", "Enable this app to show what apps are currently playing music"),
    StringSetting("deny", "Deny providers (comma separated)", ""),
], category="musicprovider")

art_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "art")
os.makedirs(art_dir, exist_ok=True)
accent_cache: dict[str, int | None] = {}


def write_art(path: str, data: bytes) -> None:
    with open(path, "wb") as art_file:
        art_file.write(data)


@dataclass
class LocalTrack:
    provider: str
    id: str
    title: str
    artist: str
    album: str
    duration: int
    position: int
    playing: bool
    art_url: str | None


def denied(provider: str) -> bool:
    denied_providers = app.settings["deny"].get_value().split(",")
    return provider.casefold() in {item.strip().casefold() for item in denied_providers if item.strip()}


def set_provider_label(providers: list[str]) -> None:
    names = ", ".join(sorted(set(providers), key=str.casefold)) or "None"
    app.settings["providers"].label = "Currently playing providers: " + names


def art_id(track: LocalTrack) -> str:
    return hashlib.sha256(track.id.encode("utf-8")).hexdigest()


def get_art(track: LocalTrack) -> str | None:
    if not track.art_url:
        return None
    identifier = art_id(track)
    path = os.path.join(art_dir, identifier + ".jpg")
    if not os.path.exists(path):
        parsed = urlparse(track.art_url)
        try:
            if parsed.scheme == "file":
                source = unquote(parsed.path)
                if sys.platform == "win32" and source.startswith("/") and len(source) > 2 and source[2] == ":":
                    source = source[1:]
                if not source or not os.path.isfile(source):
                    return None
                shutil.copyfile(source, path)
            elif parsed.scheme == "" and os.path.isfile(track.art_url):
                shutil.copyfile(track.art_url, path)
            elif parsed.scheme in ("http", "https"):
                urllib.request.urlretrieve(track.art_url, path)
            elif parsed.scheme == "data":
                header, encoded = track.art_url.split(",", 1)
                if ";base64" in header.casefold():
                    write_art(path, base64.b64decode(encoded))
                else:
                    write_art(path, unquote_to_bytes(encoded))
            else:
                return None
        except (OSError, TypeError, ValueError, binascii.Error, urllib.error.URLError):
            app.logger.debug("Could not read local album art", exc_info=True)
            return None
    if identifier not in accent_cache:
        try:
            accent_cache[identifier] = get_accent(path)
        except (OSError, ValueError):
            accent_cache[identifier] = None
    return "/apps/localmusic/art/" + identifier + ".jpg"


def update_playback(track: LocalTrack | None) -> None:
    if track is None:
        playback.reset()
        return
    artists = [Artist("local", track.artist, track.artist)]
    album = Album(
        "local",
        hashlib.sha256((track.album + track.artist).encode("utf-8")).hexdigest(),
        track.album,
        artists,
        get_art(track),
        accent_cache.get(art_id(track)),
    )
    playback.update(
        Song("local", track.id, track.title, album, artists, track.duration),
        track.playing,
        track.position,
    )


async def windows_track() -> LocalTrack | None:
    from winsdk.windows.media.control import (  # type: ignore[import-not-found]
        GlobalSystemMediaTransportControlsSessionManager,
    )
    from winsdk.windows.storage.streams import DataReader  # type: ignore[import-not-found]

    manager = await GlobalSystemMediaTransportControlsSessionManager.request_async()
    sessions = manager.get_sessions()
    candidates = []
    playing_providers = []
    for session in sessions:
        properties = await session.try_get_media_properties_async()
        if properties.title:
            provider = str(session.source_app_user_model_id or "Unknown")
            status = str(session.get_playback_info().playback_status)
            if status.endswith("PLAYING"):
                playing_providers.append(provider)
            candidates.append((session, properties, provider, status))
    set_provider_label(playing_providers)
    candidates = [candidate for candidate in candidates if not denied(candidate[2])]
    selected = next((candidate for candidate in candidates if candidate[3].endswith("PLAYING")), None)
    if selected is None and candidates:
        selected = candidates[0]
    if selected is None:
        return None
    selected, selected_properties, provider, status = selected

    art_url = None
    if selected_properties.thumbnail:
        try:
            stream = await selected_properties.thumbnail.open_read_async()
            reader = DataReader(stream)
            await reader.load_async(stream.size)
            buffer = bytearray(stream.size)
            reader.read_bytes(buffer)
            data = bytes(buffer)
            reader.close()

            identifier = hashlib.sha256(
                (selected_properties.title + selected_properties.album_title).encode("utf-8")
            ).hexdigest()
            await asyncio.to_thread(
                write_art,
                os.path.join(art_dir, identifier + ".jpg"),
                data,
            )
            art_url = Path(art_dir, identifier + ".jpg").as_uri()
        except (OSError, ValueError):
            app.logger.debug("Could not read Windows album art", exc_info=True)

    timeline = selected.get_timeline_properties()
    position = int(timeline.position.total_seconds() * 1000)
    duration = int(timeline.end_time.total_seconds() * 1000)
    status = str(selected.get_playback_info().playback_status)
    return LocalTrack(
        provider,
        str(selected_properties.track_number) + ":" + selected_properties.title,
        selected_properties.title,
        selected_properties.artist,
        selected_properties.album_title or "Unknown album",
        duration,
        position,
        status.endswith("PLAYING"),
        art_url,
    )


async def linux_track(bus) -> LocalTrack | None:
    from dbus_next import Message

    names = await bus.call(Message(destination="org.freedesktop.DBus", path="/org/freedesktop/DBus", interface="org.freedesktop.DBus", member="ListNames"))
    services = [name for name in names.body[0] if name.startswith("org.mpris.MediaPlayer2.")]
    candidates = []
    playing_providers = []
    for service in services:
        try:
            reply = await bus.call(Message(
                destination=service,
                path="/org/mpris/MediaPlayer2",
                interface="org.freedesktop.DBus.Properties",
                member="GetAll",
                signature="s",
                body=["org.mpris.MediaPlayer2.Player"],
            ))
            values = {key: value.value for key, value in reply.body[0].items()}
            metadata = {key: value.value for key, value in values["Metadata"].items()}
            title = metadata.get("xesam:title")
            if not title:
                continue
            artist = (metadata.get("xesam:artist") or ["Unknown artist"])[0]
            status = values.get("PlaybackStatus")
            provider = service.removeprefix("org.mpris.MediaPlayer2.")
            if status == "Playing":
                playing_providers.append(provider)
            duration = int(metadata.get("mpris:length", 0) / 1000)
            position = int(values.get("Position", 0) / 1000)
            candidates.append(LocalTrack(
                provider,
                str(metadata.get("mpris:trackid", title)),
                title,
                artist,
                metadata.get("xesam:album", "Unknown album"),
                duration,
                position,
                status == "Playing",
                metadata.get("mpris:artUrl"),
            ))
        except (KeyError, TypeError, ValueError, OSError):
            app.logger.debug("Could not read MPRIS player %s", service, exc_info=True)
    set_provider_label(playing_providers)
    candidates = [candidate for candidate in candidates if not denied(candidate.provider)]
    return next((candidate for candidate in candidates if candidate.playing), None) or (candidates[0] if candidates else None)


def music_thread() -> None:
    if sys.platform == "win32":
        while True:
            time.sleep(1)
            if not app.settings["enabled"].get_value():
                continue
            try:
                update_playback(asyncio.run(windows_track()))
            except ModuleNotFoundError:
                app.logger.warning("Local Music requires the winsdk package on Windows")
                return
            except (OSError, RuntimeError, TypeError, ValueError):
                app.logger.debug("Could not read Windows media session", exc_info=True)
    elif sys.platform == "linux":
        try:
            asyncio.run(linux_loop())
        except ModuleNotFoundError:
            app.logger.warning("Local Music requires the dbus-next package on Linux")


async def linux_loop() -> None:
    from dbus_next.aio import MessageBus

    try:
        bus = await MessageBus().connect()
    except (OSError, RuntimeError):
        app.logger.warning("Local Music requires a running Linux D-Bus session")
        return
    while True:
        await asyncio.sleep(1)
        if not app.settings["enabled"].get_value():
            continue
        try:
            update_playback(await linux_track(bus))
        except Exception:
            app.logger.debug("Could not read MPRIS media session", exc_info=True)


@app.blueprint.route("/art/<string:filename>")
def art_route(filename: str):
    path = os.path.join(art_dir, filename)
    if not os.path.isfile(path) or os.path.dirname(os.path.abspath(path)) != os.path.abspath(art_dir):
        return abort(404)
    return send_file(path)


if sys.platform in ("win32", "linux"):
    threading.Thread(target=music_thread, daemon=True).start()