"""Discord desktop voice controls via Discord's local RPC IPC interface."""

from __future__ import annotations

import ctypes
import json
import os
import queue
import select
import socket
import struct
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from pything.app import App
from pything.settings import StringSetting
from pything.web import render_template

app = App(
    [
        StringSetting(
            "client_id",
            "Discord application ID (from the Discord Developer Portal)",
            "",
        ),
        StringSetting("username", "Fallback display name", "You"),
        StringSetting("avatar", "Fallback avatar image URL (optional)", ""),
        StringSetting("channel", "Fallback channel name", "General"),
    ]
)

_commands: queue.Queue[dict[str, Any]] = queue.Queue()
_rpc_connected = threading.Event()


@app.blueprint.route("/launch")
def launch():
    return render_template(
        f"{app.dirname}/pages/voice.html",
        username=app.settings["username"].get_value(),
        avatar=app.settings["avatar"].get_value(),
        channel=app.settings["channel"].get_value(),
    )


def _ipc_paths() -> list[str]:
    if sys.platform == "win32":
        return [rf"\\?\pipe\discord-ipc-{i}" for i in range(10)]
    paths = []
    if sys.platform == "darwin":
        roots = [
            Path.home() / "Library/Application Support/discord",
            Path.home() / "Library/Application Support/discordcanary",
            Path.home() / "Library/Application Support/discordptb",
        ]
        paths.extend(str(root / f"discord-ipc-{i}") for root in roots for i in range(10))
    else:
        runtime = os.environ.get("XDG_RUNTIME_DIR")
        if runtime:
            paths.extend(str(Path(runtime) / f"discord-ipc-{i}") for i in range(10))
        paths.extend(f"/run/user/{os.getuid()}/discord-ipc-{i}" for i in range(10))
        paths.extend(f"/tmp/discord-ipc-{i}" for i in range(10))
    return paths


class _DiscordIPC:
    """Small nonblocking transport for Discord's 8-byte framed local IPC."""

    def __init__(self, endpoint: str):
        self.endpoint = endpoint
        self.buffer = bytearray()
        self.sock: socket.socket | None = None
        self.handle = None
        if sys.platform == "win32":
            self._open_pipe(endpoint)
        else:
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.sock.settimeout(1.0)
            self.sock.connect(endpoint)
            self.sock.setblocking(False)

    def _open_pipe(self, endpoint: str) -> None:
        kernel32 = ctypes.windll.kernel32
        handle_type = ctypes.c_void_p
        dword_type = ctypes.c_ulong
        kernel32.CreateFileW.argtypes = [
            ctypes.c_wchar_p,
            dword_type,
            dword_type,
            ctypes.c_void_p,
            dword_type,
            dword_type,
            handle_type,
        ]
        kernel32.CreateFileW.restype = handle_type
        kernel32.PeekNamedPipe.argtypes = [
            handle_type,
            ctypes.c_void_p,
            dword_type,
            ctypes.c_void_p,
            ctypes.POINTER(dword_type),
            ctypes.c_void_p,
        ]
        kernel32.ReadFile.argtypes = [
            handle_type,
            ctypes.c_void_p,
            dword_type,
            ctypes.POINTER(dword_type),
            ctypes.c_void_p,
        ]
        kernel32.WriteFile.argtypes = kernel32.ReadFile.argtypes
        kernel32.CloseHandle.argtypes = [handle_type]
        handle = kernel32.CreateFileW(
            endpoint, 0xC0000000, 0, None, 3, 0, None  # read/write, OPEN_EXISTING
        )
        if handle == ctypes.c_void_p(-1).value:
            raise OSError(ctypes.get_last_error(), f"Could not open {endpoint}")
        self.handle = handle

    def send(self, opcode: int, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        packet = struct.pack("<II", opcode, len(data)) + data
        if self.sock is not None:
            self.sock.sendall(packet)
            return
        written = ctypes.c_ulong()
        buf = ctypes.create_string_buffer(packet)
        if not ctypes.windll.kernel32.WriteFile(
            self.handle, buf, len(packet), ctypes.byref(written), None
        ) or written.value != len(packet):
            raise OSError(ctypes.get_last_error(), "Discord IPC write failed")

    def poll(self, timeout: float) -> list[tuple[int, dict[str, Any]]]:
        if self.sock is not None:
            readable, _, _ = select.select([self.sock], [], [], timeout)
            if readable:
                chunk = self.sock.recv(65536)
                if not chunk:
                    raise ConnectionError("Discord closed its IPC connection")
                self.buffer.extend(chunk)
        else:
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                available = ctypes.c_ulong()
                ok = ctypes.windll.kernel32.PeekNamedPipe(
                    self.handle, None, 0, None, ctypes.byref(available), None
                )
                if not ok:
                    raise ConnectionError("Discord closed its IPC connection")
                if available.value:
                    buf = ctypes.create_string_buffer(min(available.value, 65536))
                    received = ctypes.c_ulong()
                    if not ctypes.windll.kernel32.ReadFile(
                        self.handle, buf, len(buf), ctypes.byref(received), None
                    ):
                        raise ConnectionError("Discord IPC read failed")
                    self.buffer.extend(buf.raw[: received.value])
                    break
                time.sleep(0.025)

        frames = []
        while len(self.buffer) >= 8:
            opcode, length = struct.unpack_from("<II", self.buffer)
            if length > 8 * 1024 * 1024:
                raise ValueError("Discord IPC frame was too large")
            if len(self.buffer) < 8 + length:
                break
            payload = bytes(self.buffer[8 : 8 + length])
            del self.buffer[: 8 + length]
            if opcode in (1, 2):
                try:
                    frames.append((opcode, json.loads(payload.decode("utf-8"))))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    app.logger.warning("Ignoring invalid JSON from Discord IPC")
        return frames

    def close(self) -> None:
        if self.sock is not None:
            self.sock.close()
        elif self.handle:
            ctypes.windll.kernel32.CloseHandle(self.handle)
            self.handle = None


def _avatar_url(user: dict[str, Any]) -> str:
    user_id = str(user.get("id", ""))
    avatar = user.get("avatar")
    if user_id and avatar:
        return f"https://cdn.discordapp.com/avatars/{user_id}/{avatar}.png?size=128"
    if user_id:
        try:
            index = int(user.get("discriminator", "0")) % 5
        except (TypeError, ValueError):
            index = 0
        return f"https://cdn.discordapp.com/embed/avatars/{index}.png"
    return ""


class _VoiceRPC:
    def __init__(self, ipc: _DiscordIPC):
        self.ipc = ipc
        self.user: dict[str, Any] = {}
        self.channel: dict[str, Any] | None = None
        self.voice_states: dict[str, dict[str, Any]] = {}
        self.speaking: set[str] = set()
        self.last_spoke: dict[str, float] = {}
        self.muted = False
        self.deafened = False
        self.last_channel_id: str | None = None

    def command(self, name: str, args: dict[str, Any] | None = None) -> None:
        self.ipc.send(
            1,
            {
                "cmd": name,
                "args": args or {},
                "nonce": str(uuid.uuid4()),
            },
        )

    def subscribe(self) -> None:
        for event in (
            "VOICE_CHANNEL_SELECT",
            "VOICE_STATE_CREATE",
            "VOICE_STATE_UPDATE",
            "VOICE_STATE_DELETE",
            "SPEAKING_START",
            "SPEAKING_STOP",
            "VOICE_SETTINGS_UPDATE",
        ):
            self.command("SUBSCRIBE", {"evt": event})
        self.refresh()

    def refresh(self) -> None:
        self.command("GET_SELECTED_VOICE_CHANNEL")
        self.command("GET_VOICE_SETTINGS")

    def process(self, message: dict[str, Any]) -> None:
        event = message.get("evt")
        data = message.get("data") or {}
        if event == "READY":
            self.user = data.get("user") or {}
            self.subscribe()
        elif event == "ERROR":
            app.logger.warning("Discord RPC error: %s", data.get("message", data))
        elif event == "VOICE_SETTINGS_UPDATE":
            settings = data.get("voice_settings") or data
            self.muted = bool(settings.get("mute", self.muted))
            self.deafened = bool(settings.get("deaf", self.deafened))
        elif event == "VOICE_CHANNEL_SELECT":
            if data.get("channel_id"):
                self._set_channel({"id": data["channel_id"], "name": data.get("name", "")})
            else:
                self._set_channel(None)
        elif event in ("VOICE_STATE_CREATE", "VOICE_STATE_UPDATE", "VOICE_STATE_DELETE"):
            state = data.get("voice_state") or data
            user_id = str(state.get("user_id") or data.get("user_id") or "")
            if event == "VOICE_STATE_DELETE":
                self.voice_states.pop(user_id, None)
                self.speaking.discard(user_id)
                self.last_spoke.pop(user_id, None)
            elif user_id:
                self.voice_states[user_id] = state
        elif event in ("SPEAKING_START", "SPEAKING_STOP"):
            user_id = str(data.get("user_id") or "")
            if user_id:
                if event == "SPEAKING_START":
                    self.speaking.add(user_id)
                    self.last_spoke[user_id] = time.monotonic()
                else:
                    self.speaking.discard(user_id)
        elif message.get("cmd") == "GET_SELECTED_VOICE_CHANNEL":
            self._set_channel(data)
        elif message.get("cmd") == "GET_VOICE_SETTINGS":
            settings = data.get("voice_settings") or data
            self.muted = bool(settings.get("mute", self.muted))
            self.deafened = bool(settings.get("deaf", self.deafened))

    def _set_channel(self, data: Any) -> None:
        if not isinstance(data, dict) or not data.get("id"):
            self.channel = None
            self.voice_states.clear()
            self.speaking.clear()
            self.last_spoke.clear()
            return
        self.channel = data
        self.last_channel_id = str(data["id"])
        states = data.get("voice_states") or []
        if isinstance(states, dict):
            states = list(states.values())
        if isinstance(states, list):
            current = {}
            for state in states:
                if not isinstance(state, dict):
                    continue
                user = state.get("user") or {}
                user_id = str(state.get("user_id") or user.get("id") or "")
                if user_id:
                    current[user_id] = state
            self.voice_states = current
            self.speaking.intersection_update(current)
            self.last_spoke = {
                user_id: stamp
                for user_id, stamp in self.last_spoke.items()
                if user_id in current
            }

    def execute(self, payload: dict[str, Any]) -> None:
        action = payload.get("action")
        if action == "mute":
            self.muted = bool(payload.get("muted", not self.muted))
            self.command("SET_VOICE_SETTINGS", {"mute": self.muted, "deaf": self.deafened})
        elif action == "deafen":
            self.deafened = bool(payload.get("deafened", not self.deafened))
            self.command("SET_VOICE_SETTINGS", {"mute": self.muted, "deaf": self.deafened})
        elif action == "leave":
            if self.channel:
                self.last_channel_id = str(self.channel.get("id"))
            self.command("SELECT_VOICE_CHANNEL", {"channel_id": None})
        elif action == "rejoin" and self.last_channel_id:
            self.command("SELECT_VOICE_CHANNEL", {"channel_id": self.last_channel_id})
        elif action == "refresh":
            self.refresh()

    def snapshot(self) -> dict[str, Any]:
        user_id = str(self.user.get("id", ""))
        own_voice = self.voice_states.get(user_id, {})
        user_name = (
            self.user.get("global_name")
            or self.user.get("username")
            or app.settings["username"].get_value()
        )
        own_avatar = _avatar_url(self.user) or app.settings["avatar"].get_value()
        channel = self.channel or {}
        speakers = []
        ordered = sorted(
            (speaker_id for speaker_id in self.last_spoke if speaker_id != user_id),
            key=self.last_spoke.get,
            reverse=True,
        )
        for speaker_id in ordered[:3]:
            state = self.voice_states.get(speaker_id, {})
            user = state.get("user") or {}
            name = state.get("nick") or user.get("global_name") or user.get("username") or "Discord user"
            speakers.append(
                {
                    "name": name,
                    "avatar": _avatar_url(user),
                    "speaking": speaker_id in self.speaking,
                }
            )
        return {
            "connected": True,
            "channel": channel.get("name") or app.settings["channel"].get_value(),
            "in_call": bool(self.channel),
            "self": {
                "name": user_name,
                "avatar": own_avatar,
                "muted": bool(own_voice.get("mute", self.muted)),
                "deafened": bool(own_voice.get("deaf", self.deafened)),
                "speaking": user_id in self.speaking,
            },
            "speakers": speakers,
        }


def _publish_disconnected(message: str) -> None:
    app.send(
        "voice_state",
        {
            "connected": False,
            "error": message,
            "channel": app.settings["channel"].get_value(),
            "in_call": False,
            "self": {
                "name": app.settings["username"].get_value(),
                "avatar": app.settings["avatar"].get_value(),
                "muted": False,
                "deafened": False,
                "speaking": False,
            },
            "speakers": [],
        },
    )


def _rpc_thread() -> None:
    while True:
        if not app.should_poll():
            time.sleep(0.5)
            continue
        client_id = app.settings["client_id"].get_value().strip()
        if not client_id:
            _publish_disconnected("Set a Discord application ID in app settings")
            time.sleep(3)
            continue

        ipc = None
        try:
            last_error: Exception | None = None
            for endpoint in _ipc_paths():
                try:
                    ipc = _DiscordIPC(endpoint)
                    break
                except OSError as exc:
                    last_error = exc
            if ipc is None:
                raise ConnectionError("Discord desktop IPC not found; is Discord running?") from last_error

            ipc.send(0, {"v": 1, "client_id": client_id})
            rpc = _VoiceRPC(ipc)
            ready_deadline = time.monotonic() + 8
            while time.monotonic() < ready_deadline and not rpc.user:
                for _, message in ipc.poll(0.25):
                    rpc.process(message)
            if not rpc.user:
                raise ConnectionError("Discord RPC handshake timed out; check the application ID")
            _rpc_connected.set()
            app.send("voice_state", rpc.snapshot())
            next_refresh = time.monotonic() + 2
            while app.should_poll():
                for _, message in ipc.poll(0.15):
                    rpc.process(message)
                while True:
                    try:
                        command = _commands.get_nowait()
                    except queue.Empty:
                        break
                    rpc.execute(command)
                if time.monotonic() >= next_refresh:
                    rpc.refresh()
                    next_refresh = time.monotonic() + 2
                app.send("voice_state", rpc.snapshot())
        except Exception as exc:  # noqa: BLE001
            app.logger.info("Discord RPC unavailable: %s", exc)
            _publish_disconnected(str(exc))
            time.sleep(2)
        finally:
            _rpc_connected.clear()
            if ipc:
                ipc.close()


@app.on("refresh")
def on_refresh(_data=None):
    # A refresh is just a prompt to query Discord on the next IPC pass.
    _commands.put({"action": "refresh"})


@app.on("command")
def on_command(command):
    if not isinstance(command, dict) or command.get("action") not in {
        "mute",
        "deafen",
        "leave",
        "rejoin",
    }:
        return
    if not _rpc_connected.is_set():
        app.logger.debug("Ignoring Discord control while Discord RPC is disconnected")
        return
    _commands.put(command)


@app.on_startup
def start_rpc():
    threading.Thread(target=_rpc_thread, daemon=True, name="discord-rpc").start()
