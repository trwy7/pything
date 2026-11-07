import asyncio
import base64
import binascii
import hashlib
import io
import os
import re
import shutil
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from urllib.parse import unquote, unquote_to_bytes, urlparse

from apps.music.types import Album, Artist, Song, playback
from apps.music.utils import get_accent
from PIL import Image

from pything import App, LabelSetting, StringSetting, abort, send_file

app = App(
    [
        LabelSetting(
            "providers", "Enable this app to show what apps are currently playing music"
        ),
        StringSetting("deny", "Deny providers (comma separated)", ""),
    ],
)

art_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "art")
os.makedirs(art_dir, exist_ok=True)
accent_cache: dict[str, int | None] = {}
windows_position_cache: dict[str, tuple[int, int, float]] = {}
switch_delay = 0.5
playback_lock = threading.Lock()
current_provider: str | None = None
pending_active = False
pending_generation = 0


def write_art(path: str, data: bytes) -> None:
    with open(path, "wb") as art_file:
        art_file.write(data)


def write_thumbnail(path: str, data: bytes) -> None:
    with Image.open(io.BytesIO(data)) as image:
        image.convert("RGB").save(path, format="JPEG")


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


pending_track: LocalTrack | None = None


def denied(provider: str) -> bool:
    denied_providers = app.settings["deny"].get_value().split(",")
    return provider.casefold() in {
        item.strip().casefold() for item in denied_providers if item.strip()
    }


def set_provider_label(providers: list[str]) -> None:
    names = ", ".join(sorted(set(providers), key=str.casefold)) or "None"
    app.settings["providers"].label = "Currently playing providers: " + names


def get_artists(artist_names: str) -> list[Artist]:
    names = [name.strip() for name in re.split(r"[,;/]", artist_names) if name.strip()]
    return [Artist("local", name, name) for name in names]


@lru_cache(maxsize=1024)
def cached_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def song_id(track: LocalTrack) -> str:
    return cached_sha256(
        f"{track.provider}\0{track.id}\0{track.title}\0{track.artist}\0{track.album}"
    )


def art_id(track: LocalTrack) -> str:
    return cached_sha256(
        track.art_url or (track.id + track.title + track.artist + track.album)
    )


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
                if (
                    sys.platform == "win32"
                    and source.startswith("/")
                    and len(source) > 2
                    and source[2] == ":"
                ):
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


def apply_playback(track: LocalTrack | None) -> None:
    if track is None:
        playback.reset()
        return
    artists = get_artists(track.artist)
    album = Album(
        "local",
        cached_sha256(track.album + track.artist),
        track.album,
        artists,
        get_art(track),
        accent_cache.get(art_id(track)),
    )
    playback.update(
        Song("local", song_id(track), track.title, album, artists, track.duration),
        track.playing,
        track.position,
    )


def cancel_pending() -> None:
    global pending_active, pending_generation, pending_track
    if pending_active:
        app.logger.debug(
            "Canceling pending playback provider switch to %s",
            pending_track.provider if pending_track is not None else None,
        )
    pending_active = False
    pending_track = None
    pending_generation += 1


def commit_pending(generation: int) -> None:
    global current_provider, pending_active, pending_track
    with playback_lock:
        if not pending_active or generation != pending_generation:
            return
        track = pending_track
        provider = track.provider if track is not None else None
        app.logger.debug(
            "Switching playback provider from %s to %s after delay",
            current_provider,
            provider,
        )
        pending_active = False
        pending_track = None
        current_provider = provider
        apply_playback(track)


def update_playback(track: LocalTrack | None) -> None:
    global current_provider, pending_active, pending_generation, pending_track
    with playback_lock:
        provider = track.provider if track is not None else None
        if provider == current_provider:
            cancel_pending()
            apply_playback(track)
            return
        if current_provider is None:
            app.logger.debug("Applying playback provider %s", provider)
            cancel_pending()
            current_provider = provider
            apply_playback(track)
            return
        if pending_active:
            pending_provider = (
                pending_track.provider if pending_track is not None else None
            )
            if pending_provider != provider:
                app.logger.debug(
                    "Updating pending playback provider switch from %s to %s",
                    pending_provider,
                    provider,
                )
            pending_track = track
            return
        app.logger.debug(
            "Playback provider changed from %s to %s; waiting %.1fs before switching",
            current_provider,
            provider,
            switch_delay,
        )
        pending_active = True
        pending_track = track
        pending_generation += 1
        generation = pending_generation
    timer = threading.Timer(switch_delay, commit_pending, args=(generation,))
    timer.daemon = True
    timer.start()


async def windows_track(manager) -> LocalTrack | None:
    from winsdk.windows.media.control import (  # type: ignore[import-not-found]
        GlobalSystemMediaTransportControlsSessionPlaybackStatus,
    )
    from winsdk.windows.storage.streams import DataReader  # type: ignore[import-not-found]

    sessions = manager.get_sessions() or []
    candidates = []
    playing_providers = []
    for session in sessions:
        properties = await session.try_get_media_properties_async()
        if properties.title:
            provider = str(session.source_app_user_model_id or "Unknown")
            status = session.get_playback_info().playback_status
            if (
                status
                == GlobalSystemMediaTransportControlsSessionPlaybackStatus.PLAYING
            ):
                playing_providers.append(provider)
            candidates.append((session, properties, provider, status))
    set_provider_label(playing_providers)
    candidates = [candidate for candidate in candidates if not denied(candidate[2])]
    selected = next(
        (
            candidate
            for candidate in candidates
            if candidate[3]
            == GlobalSystemMediaTransportControlsSessionPlaybackStatus.PLAYING
        ),
        None,
    )
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

            identifier = hashlib.sha256(data).hexdigest()
            await asyncio.to_thread(
                write_thumbnail,
                os.path.join(art_dir, identifier + ".jpg"),
                data,
            )
            art_url = Path(art_dir, identifier + ".jpg").as_uri()
        except (OSError, ValueError):
            app.logger.debug("Could not read Windows album art", exc_info=True)

    playback_info = selected.get_playback_info()
    status = playback_info.playback_status
    timeline = selected.get_timeline_properties()
    track_key = provider + ":" + selected_properties.title
    now_monotonic = time.monotonic()
    playback_rate = float(getattr(playback_info, "playback_rate", None) or 1.0)
    if timeline is None:
        app.logger.debug("Windows media session has no timeline properties")
        position = 0
        duration = 0
    else:
        position = int(timeline.position.total_seconds() * 1000)
        duration = int(timeline.end_time.total_seconds() * 1000)
        if status == GlobalSystemMediaTransportControlsSessionPlaybackStatus.PLAYING:
            last_updated = timeline.last_updated_time
            if last_updated.tzinfo is None:
                last_updated = last_updated.replace(tzinfo=UTC)
            elapsed = max(0, (datetime.now(UTC) - last_updated).total_seconds())
            position += int(elapsed * playback_rate * 1000)
        position = min(position, duration) if duration else position
    reported_position = position
    cached_position = windows_position_cache.get(track_key)
    if (
        status == GlobalSystemMediaTransportControlsSessionPlaybackStatus.PLAYING
        and cached_position
        and reported_position == cached_position[0]
    ):
        position = max(
            position,
            cached_position[1]
            + int((now_monotonic - cached_position[2]) * playback_rate * 1000),
        )
    if status == GlobalSystemMediaTransportControlsSessionPlaybackStatus.PLAYING:
        windows_position_cache[track_key] = (reported_position, position, now_monotonic)
    else:
        windows_position_cache.pop(track_key, None)
    position = min(position, duration) if duration else position
    app.logger.debug(
        "Windows media session: provider=%s, title=%s, artist=%s, album=%s, position=%d, duration=%d",
        provider,
        selected_properties.title,
        selected_properties.artist,
        selected_properties.album_title,
        position,
        duration,
    )
    return LocalTrack(
        provider,
        str(selected_properties.track_number) + ":" + selected_properties.title,
        selected_properties.title,
        selected_properties.artist,
        selected_properties.album_title or "Unknown album",
        duration,
        position,
        status == GlobalSystemMediaTransportControlsSessionPlaybackStatus.PLAYING,
        art_url,
    )


async def linux_track(bus) -> LocalTrack | None:
    from dbus_next import Message

    names = await bus.call(
        Message(
            destination="org.freedesktop.DBus",
            path="/org/freedesktop/DBus",
            interface="org.freedesktop.DBus",
            member="ListNames",
        )
    )
    services = [
        name for name in names.body[0] if name.startswith("org.mpris.MediaPlayer2.")
    ]

    async def read_service(service: str) -> tuple[str, LocalTrack | None]:
        try:
            reply = await bus.call(
                Message(
                    destination=service,
                    path="/org/mpris/MediaPlayer2",
                    interface="org.freedesktop.DBus.Properties",
                    member="GetAll",
                    signature="s",
                    body=["org.mpris.MediaPlayer2.Player"],
                )
            )
            values = {key: value.value for key, value in reply.body[0].items()}
            metadata = {key: value.value for key, value in values["Metadata"].items()}
            title = metadata.get("xesam:title")
            if not title:
                return service.removeprefix("org.mpris.MediaPlayer2."), None
            artist = (metadata.get("xesam:artist") or ["Unknown artist"])[0]
            status = values.get("PlaybackStatus")
            provider = service.removeprefix("org.mpris.MediaPlayer2.")
            duration = int(metadata.get("mpris:length", 0) / 1000)
            position = int(values.get("Position", 0) / 1000)
            return provider, LocalTrack(
                provider,
                str(metadata.get("mpris:trackid", title)),
                title,
                artist,
                metadata.get("xesam:album", "Unknown album"),
                duration,
                position,
                status == "Playing",
                metadata.get("mpris:artUrl"),
            )
        except (KeyError, TypeError, ValueError, OSError):
            app.logger.debug("Could not read MPRIS player %s", service, exc_info=True)
            return service.removeprefix("org.mpris.MediaPlayer2."), None

    results = await asyncio.gather(*(read_service(service) for service in services))
    playing_providers = [
        provider for provider, candidate in results if candidate and candidate.playing
    ]
    candidates = [candidate for _, candidate in results if candidate is not None]
    set_provider_label(playing_providers)
    candidates = [
        candidate for candidate in candidates if not denied(candidate.provider)
    ]
    return next((candidate for candidate in candidates if candidate.playing), None) or (
        candidates[0] if candidates else None
    )


async def windows_loop() -> None:
    from winsdk.windows.media.control import (  # type: ignore[import-not-found]
        GlobalSystemMediaTransportControlsSessionManager,
    )

    manager = await GlobalSystemMediaTransportControlsSessionManager.request_async()
    loop = asyncio.get_running_loop()
    refresh = asyncio.Event()

    def request_refresh(*_) -> None:
        loop.call_soon_threadsafe(refresh.set)

    manager.add_current_session_changed(request_refresh)
    manager.add_sessions_changed(request_refresh)

    subscriptions = []
    while True:
        refresh.clear()
        for session, removers in subscriptions:
            for remove, token in removers:
                try:
                    remove(token)
                except Exception:
                    app.logger.debug(
                        "Could not unsubscribe from Windows media session events",
                        exc_info=True,
                    )
        subscriptions.clear()
        try:
            for session in manager.get_sessions() or []:
                removers = []
                for add, remove in (
                    (
                        session.add_media_properties_changed,
                        session.remove_media_properties_changed,
                    ),
                    (
                        session.add_playback_info_changed,
                        session.remove_playback_info_changed,
                    ),
                    (
                        session.add_timeline_properties_changed,
                        session.remove_timeline_properties_changed,
                    ),
                ):
                    removers.append((remove, add(request_refresh)))
                subscriptions.append((session, removers))
            update_playback(await windows_track(manager))
        except (OSError, RuntimeError, TypeError, ValueError):
            app.logger.debug("Could not read Windows media session", exc_info=True)
        await refresh.wait()


def music_thread() -> None:
    if sys.platform == "win32":
        while True:
            try:
                asyncio.run(windows_loop())
                return
            except ModuleNotFoundError:
                app.logger.warning("Local Music requires the winsdk package on Windows")
                time.sleep(1)
                return
            except (OSError, RuntimeError, TypeError, ValueError):
                app.logger.debug("Could not read Windows media session", exc_info=True)
            time.sleep(1)
    elif sys.platform == "linux":
        try:
            asyncio.run(linux_loop())
        except ModuleNotFoundError:
            app.logger.warning("Local Music requires the dbus-next package on Linux")


async def linux_loop() -> None:
    from dbus_next import Message, MessageType
    from dbus_next.aio import MessageBus

    try:
        bus = await MessageBus().connect()
    except (OSError, RuntimeError):
        app.logger.warning("Local Music requires a running Linux D-Bus session")
        return

    refresh = asyncio.Event()

    def on_message(message: Message) -> None:
        if message.message_type != MessageType.SIGNAL:
            return
        if (
            (
                message.interface == "org.freedesktop.DBus.Properties"
                and message.member == "PropertiesChanged"
                and message.path == "/org/mpris/MediaPlayer2"
                and message.body
                and message.body[0] == "org.mpris.MediaPlayer2.Player"
            )
            or (
                message.interface == "org.mpris.MediaPlayer2.Player"
                and message.member == "Seeked"
            )
            or (
                message.interface == "org.freedesktop.DBus"
                and message.member == "NameOwnerChanged"
                and message.body
                and str(message.body[0]).startswith("org.mpris.MediaPlayer2.")
            )
        ):
            refresh.set()

    bus.add_message_handler(on_message)
    for rule in (
        (
            "type='signal',interface='org.freedesktop.DBus.Properties',"
            "member='PropertiesChanged',path='/org/mpris/MediaPlayer2',"
            "arg0='org.mpris.MediaPlayer2.Player'"
        ),
        "type='signal',interface='org.mpris.MediaPlayer2.Player',member='Seeked'",
        (
            "type='signal',interface='org.freedesktop.DBus',"
            "member='NameOwnerChanged',arg0namespace='org.mpris.MediaPlayer2'"
        ),
    ):
        await bus.call(
            Message(
                destination="org.freedesktop.DBus",
                path="/org/freedesktop/DBus",
                interface="org.freedesktop.DBus",
                member="AddMatch",
                signature="s",
                body=[rule],
            )
        )

    while True:
        refresh.clear()
        try:
            update_playback(await linux_track(bus))
        except Exception:
            app.logger.debug("Could not read MPRIS media session", exc_info=True)
        await refresh.wait()


@app.blueprint.route("/art/<string:filename>")
def art_route(filename: str):
    path = os.path.join(art_dir, filename)
    if not os.path.isfile(path) or os.path.dirname(
        os.path.abspath(path)
    ) != os.path.abspath(art_dir):
        return abort(404)
    return send_file(path)


if sys.platform in ("win32", "linux"):

    @app.on_startup
    def start_music_thread() -> None:
        threading.Thread(target=music_thread, daemon=True).start()
