"""Raw WebSocket transport."""

from __future__ import annotations

import base64
import hashlib
import json
import struct
import threading
from collections.abc import Callable
from typing import Any

from . import state
from .web import MultiDict, _get_request

_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def _ws_accept_key(key: str) -> str:
    return base64.b64encode(hashlib.sha1((key + _WS_GUID).encode()).digest()).decode()


class WSConnection:
    """A raw websocket connection; safe to send from multiple threads."""

    def __init__(self, rfile, wfile):
        self._rfile = rfile
        self._wfile = wfile
        self._send_lock = threading.Lock()
        self._closed = False

    def send_text(self, text: str) -> None:
        payload = text.encode()
        frame = self._encode_frame(payload, opcode=0x1)
        with self._send_lock:
            if self._closed:
                raise ConnectionError("websocket closed")
            self._wfile.write(frame)
            self._wfile.flush()

    def send_json(self, obj: Any) -> None:
        self.send_text(json.dumps(obj, separators=(",", ":")))

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            with self._send_lock:
                self._wfile.write(self._encode_frame(b"", opcode=0x8))
                self._wfile.flush()
        except OSError:
            pass

    @staticmethod
    def _encode_frame(payload: bytes, opcode: int = 0x1) -> bytes:
        header = bytes([0x80 | opcode])
        n = len(payload)
        if n < 126:
            header += struct.pack("!B", n)
        elif n <= 0xFFFF:
            header += struct.pack("!B", 126) + struct.pack("!H", n)
        else:
            header += struct.pack("!B", 127) + struct.pack("!Q", n)
        return header + payload

    def _read_exact(self, n: int) -> bytes:
        data = b""
        while len(data) < n:
            chunk = self._rfile.read(n - len(data))
            if not chunk:
                raise ConnectionError("websocket closed by peer")
            data += chunk
        return data

    def recv_text(self) -> str | None:
        """Read the next text message. Returns None once the peer closes."""
        fragments = bytearray()
        while True:
            b1, b2 = self._read_exact(2)
            fin = b1 & 0x80
            opcode = b1 & 0x0F
            masked = b2 & 0x80
            length = b2 & 0x7F
            if length == 126:
                (length,) = struct.unpack("!H", self._read_exact(2))
            elif length == 127:
                (length,) = struct.unpack("!Q", self._read_exact(8))
            mask = self._read_exact(4) if masked else None
            payload = self._read_exact(length) if length else b""
            if mask is not None:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            if opcode == 0x8:  # close
                self.close()
                return None
            if opcode == 0x9:  # ping -> pong
                try:
                    with self._send_lock:
                        self._wfile.write(self._encode_frame(payload, opcode=0xA))
                        self._wfile.flush()
                except OSError:
                    return None
                continue
            if opcode == 0xA:  # pong
                continue
            if opcode in (0x1, 0x2, 0x0):  # text/binary/continuation
                fragments.extend(payload)
                if fin:
                    return fragments.decode(errors="replace")
                continue
            return None


class Socket:
    """Socket.IO-like API over raw websockets.

    Events are JSON messages of the form ``{"event": name, "args": [...]}``,
    matching the call shape of the old ``socket.emit(name, *args)`` /
    ``socket.on(name, handler)`` usage.
    """

    def __init__(self):
        self._handlers: dict[str, Callable] = {}

    def on(self, event: str):
        def decorator(func: Callable) -> Callable:
            self._handlers[event] = func
            return func

        return decorator

    def emit(self, event: str, *args: Any, to: str | None = None) -> None:
        if to is None:
            targets = list(state.clients.values())
        else:
            target = state.clients.get(to)
            targets = [target] if target else []
        for client in targets:
            try:
                client.conn.send_json({"event": event, "args": list(args)})
            except (OSError, ConnectionError):
                state.logger.debug("Could not send %s to client %s", event, client.sid)


socket = Socket()


class Client:
    def __init__(self, sid: str, conn: WSConnection) -> None:
        self.sid = sid
        self.conn = conn
        self.app = "dashboard"
        state.clients[sid] = self

    def change_app(self, app) -> None:
        # Local import to avoid a cycle with pything.app at module load time.
        from .app import App

        if isinstance(app, App):
            app = app.id
        if not isinstance(app, str):
            raise TypeError("Argument app must be a string with the ID of the app")
        self.app = app
        socket.emit("changeframe", "/apps/" + app + "/launch", to=self.sid)


def _handle_ws_message(client: Client, event: str, args: list) -> None:
    req = _get_request()
    req.sid = client.sid
    req.args = MultiDict({})
    req.form = MultiDict({})
    handler = socket._handlers.get(event)
    if handler is not None:
        state.logger.debug("WS %s <- %s %r", client.sid, event, args)
        handler(*args)
        return
    # Built-in events (formerly @socket.on handlers in this module)
    if event == "open_app":
        state.logger.debug("%s is opening %s", client.sid, args[0])
        client.change_app(args[0])
    elif event == "app_com":
        app_id, app_event, data = args
        if app_id not in state.apps:
            state.logger.error(
                "A client just sent a request to non-existent app '%s'", app_id
            )
            return
        if app_event == "debug":
            state.logger.debug("Client debug message to %s: %s", app_id, data)
            return
        if app_event not in state.apps[app_id].listeners:
            state.logger.warning(
                "A client just sent a message to '%s' with non-existent event '%s'",
                app_id,
                app_event,
            )
            return
        state.apps[app_id].listeners[app_event](data)
    elif event == "debug":
        state.logger.debug("Client message: %s", args[0] if args else "")


def _setting_value(setting, value):
    match setting.type:
        case "bool":
            if isinstance(value, bool):
                return value
            if value in ("on", "true", "1"):
                return True
            if value in ("off", "false", "0"):
                return False
            raise ValueError("Invalid boolean setting value")
        case "int":
            value = int(value)
            if setting.min_value is not None and value < setting.min_value:
                raise ValueError("Setting value is below its minimum")
            if setting.max_value is not None and value > setting.max_value:
                raise ValueError("Setting value is above its maximum")
            return value
        case "float":
            value = float(value)
            if setting.min_value is not None and value < setting.min_value:
                raise ValueError("Setting value is below its minimum")
            if setting.max_value is not None and value > setting.max_value:
                raise ValueError("Setting value is above its maximum")
            return value
        case "select":
            if value not in setting.options:
                raise ValueError("Invalid select setting value")
            return value
        case "string" | "data":
            return value
        case _:
            raise ValueError("Setting cannot be changed")


def _handle_setting_message(message: Any) -> None:
    if not isinstance(message, dict):
        raise TypeError("Expected a JSON object")
    app_id = message.get("app")
    setting_id = message.get("setting")
    if not isinstance(app_id, str) or not isinstance(setting_id, str):
        raise TypeError("'app' and 'setting' must be strings")
    if "value" not in message:
        raise ValueError("Missing setting value")
    app = state.apps.get(app_id)
    if app is None or setting_id not in app.settings:
        raise ValueError("Unknown app or setting")
    setting = app.settings[setting_id]
    value = _setting_value(setting, message["value"])
    for listener in app.settingmodifylisteners:
        listener({setting_id: value})
    state.logger.debug("temporarily setting %s.%s to %r", app_id, setting_id, value)


def _run_settings_ws_connection(conn: WSConnection) -> None:
    """Receive setting updates without sending application data to the client."""
    req = _get_request()
    req.sid = None
    req.args = MultiDict({})
    req.form = MultiDict({})
    try:
        while True:
            try:
                text = conn.recv_text()
            except (OSError, ConnectionError):
                break
            if text is None:
                break
            try:
                _handle_setting_message(json.loads(text))
            except (json.JSONDecodeError, TypeError, ValueError, KeyError) as exc:
                state.logger.warning(
                    "Ignoring invalid settings websocket message: %s", exc
                )
            except Exception:  # noqa: BLE001
                state.logger.exception("Error processing settings websocket message")
    finally:
        conn.close()


def _run_ws_connection(rfile, wfile, client: Client) -> None:
    try:
        while True:
            try:
                text = client.conn.recv_text()
            except (OSError, ConnectionError):
                break
            if text is None:
                break
            try:
                message = json.loads(text)
            except json.JSONDecodeError:
                state.logger.warning(
                    "Ignoring invalid websocket message from %s", client.sid
                )
                continue
            args = message.get("args", [])
            if not isinstance(args, list):
                args = [args]
            _handle_ws_message(client, message.get("event", ""), args)
    finally:
        state.clients.pop(client.sid, None)
        client.conn.close()
        state.logger.debug("Client %s disconnected", client.sid)
