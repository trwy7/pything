import base64
import datetime
import hashlib
import importlib
import inspect
import json
import logging
import mimetypes
import os
import pickle
import re
import shutil
import struct
import sys
import threading
import time
import urllib.parse
from collections.abc import Callable, Generator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import truststore
from jinja2 import ChoiceLoader, Environment, FileSystemLoader

from .depends import install_app_requirements
from .utils import CACHE_ROOT  # noqa: F401 # imported for other apps

truststore.inject_into_ssl()

sys.modules["pything"] = sys.modules[__name__]

DEVMODE = bool(os.environ.get("DEV", False))  # noqa: PLW1508
logging.basicConfig(level=logging.DEBUG if DEVMODE else logging.INFO)
logger = logging.getLogger("pything")
if os.name == "nt":
    config_dir = os.path.join(os.environ["APPDATA"], "pything")
    old_data_path = os.path.join(os.environ["APPDATA"], "pything.pkl")
else:
    config_dir = os.path.join(os.path.expanduser("~"), ".config", "pything")
    old_data_path = os.path.join(os.path.expanduser("~"), ".config", "pything.pkl")
data_path = os.path.join(config_dir, "data.pkl")
APP_CONFIG_ID = "_apps"
RESTART_EXIT_CODE = 65
HOST = "127.0.0.1"
PORT = 5192

if os.path.exists(old_data_path) and not os.path.exists(data_path):
    os.makedirs(config_dir, exist_ok=True)
    shutil.move(old_data_path, data_path)

os.chdir(os.path.dirname(os.path.abspath(__file__)))  # sanity check

# Let apps load templates from their own directories
base_dir = os.path.dirname(os.path.abspath(__file__))
# Apps are imported by their top-level ``apps.*`` names, so expose the package
# directory as an import root both in source checkouts and installed wheels.
sys.path.insert(0, base_dir)

jinja_env = Environment(
    loader=ChoiceLoader(
        [
            FileSystemLoader(os.path.join(base_dir, "pages").replace("\\", "/")),
            FileSystemLoader(os.path.join(base_dir, "apps").replace("\\", "/")),
            FileSystemLoader(os.path.join(base_dir, "customapps").replace("\\", "/")),
        ]
    ),
    autoescape=False,
)

# Templates that include per-app mod fragments (clientmod/appmod) are rendered
# once per owning app so each fragment sees its own ``app``. The pre-rendered
# HTML is injected as ``mods_html`` / ``app_mods_html``.
def _render_template(name: str, **ctx: Any) -> str:
    ctx.setdefault("apps", apps)
    ctx.setdefault("app_mods", app_mods)
    if "app" not in ctx and _get_current_app() is not None:
        ctx["app"] = _get_current_app()
    ctx.setdefault("request", request)
    if ctx.get("mods"):
        ctx["mods_html"] = [
            _render_template(mod, **{**ctx, "app": mod_app, "mods": None})
            for mod, mod_app in ctx["mods"]
        ]
        del ctx["mods"]
    if ctx.get("app_mods"):
        ctx["app_mods_html"] = [
            _render_template(mod, **{**ctx, "app": mod_app, "app_mods": None})
            for mod, mod_app in ctx["app_mods"]
        ]
        del ctx["app_mods"]
    return jinja_env.get_template(name).render(**ctx)


class Abort(Exception):
    def __init__(self, status: int):
        self.status = status


def abort(status: int):
    raise Abort(status)


class Response:
    def __init__(
        self,
        body: bytes = b"",
        status: int = 200,
        content_type: str = "text/html; charset=utf-8",
        headers: dict[str, str] | None = None,
    ):
        if isinstance(body, str):
            body = body.encode()
        self.body = body
        self.status = status
        self.content_type = content_type
        self.headers = headers or {}


def render_template(name: str, **ctx: Any) -> Response:
    return Response(_render_template(name, **ctx))


def redirect(location: str) -> Response:
    return Response(status=303, headers={"Location": location})


def send_file(path: str) -> Response:
    content_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
    with open(path, "rb") as file:
        return Response(file.read(), content_type=content_type)


class MultiDict:
    """Minimal dict-like wrapper over ``parse_qs`` output (values are lists)."""

    def __init__(self, data: dict[str, list[str]]):
        self._data = data

    def __contains__(self, key: str) -> bool:
        return key in self._data

    def __getitem__(self, key: str) -> str:
        return self._data[key][0]

    def get(self, key: str, default: Any = None) -> Any:
        values = self._data.get(key)
        return values[0] if values else default

    def __iter__(self):
        return iter(self._data)

    def __repr__(self):
        return f"MultiDict({self._data!r})"


class _Request:
    """Request shim: args/form for HTTP routes, sid for websocket dispatches."""

    def __init__(self):
        self.args: MultiDict = MultiDict({})
        self.form: MultiDict = MultiDict({})
        self.sid: str | None = None


_local = threading.local()


def _get_request() -> _Request:
    req = getattr(_local, "request", None)
    if req is None:
        req = _Request()
        _local.request = req
    return req


def _get_current_app() -> "App | None":
    return getattr(_local, "current_app", None)


def _set_current_app(app: "App | None") -> None:
    _local.current_app = app


class _RequestProxy:
    """Thread-local proxy so ``request`` always reflects the active request."""

    def __getattr__(self, name: str) -> Any:
        return getattr(_get_request(), name)


request = _RequestProxy()


class Blueprint:
    """Minimal stand-in for flask.Blueprint.

    ``route`` collects handlers that get registered under the app's prefix
    (``/apps/<id>``) when the app is imported.
    """

    def __init__(self, name: str, import_name: str, static_folder: str | None = None):
        self.name = name
        self.static_folder = static_folder
        self._routes: list[tuple[str, tuple[str, ...], Callable]] = []

    def route(self, path: str, methods: tuple[str, ...] = ("GET",)):
        def decorator(func: Callable) -> Callable:
            self._routes.append((path, methods, func))
            return func

        return decorator

    def context_processor(self, func: Callable) -> Callable:
        # Templates always receive ``app`` from render_template; accepted for
        # compatibility so existing apps keep working.
        return func


_converters = {
    "string": ("[^/]+", str),
    "int": (r"\d+", int),
    "path": (".+", str),
}


def _compile_route(path: str) -> tuple["re.Pattern", dict[str, Callable]]:
    converters: dict[str, Callable] = {}

    def repl(match: "re.Match") -> str:
        kind, name = match.group(1), match.group(2)
        pattern, conv = _converters.get(kind, ("[^/]+", str))
        converters[name] = conv
        return f"(?P<{name}>{pattern})"

    regex = re.sub(r"<(?:(\w+):)?(\w+)>", repl, path)
    return re.compile("^" + regex + "$"), converters


# (methods, regex, converters, handler, owning app id or None)
_routes: list[tuple[set[str], "re.Pattern", dict[str, Callable], Callable, str | None]] = []


def route(path: str, methods: tuple[str, ...] = ("GET",)):
    def decorator(func: Callable) -> Callable:
        regex, converters = _compile_route(path)
        _routes.append((set(methods), regex, converters, func, None))
        return func

    return decorator


def _register_blueprint_routes(blueprint: Blueprint, prefix: str, app_id: str) -> None:
    for path, methods, func in blueprint._routes:
        regex, converters = _compile_route(prefix + path)
        _routes.append((set(methods), regex, converters, func, app_id))


def _dispatch(method: str, path: str) -> Response | None:
    """Match a request against registered routes. Returns None if no match."""
    for methods, regex, converters, handler, app_id in _routes:
        if method not in methods:
            continue
        match = regex.match(path)
        if not match:
            continue
        kwargs = {
            name: converters[name](value) for name, value in match.groupdict().items()
        }
        if app_id is not None and app_id in apps:
            _set_current_app(apps[app_id])
        try:
            result = handler(**kwargs)
        except Abort as exc:
            return Response(f"Error {exc.status}", status=exc.status)
        except Exception:
            logger.exception("Unhandled error in route %s %s", method, path)
            return Response("Internal server error", status=500)
        if isinstance(result, Response):
            return result
        if isinstance(result, (str, bytes)):
            return Response(result)
        if result is None:
            return Response(b"", status=200)
        return Response(str(result))
    return None


_static_dir = os.path.join(base_dir, "static")


def _serve_static(path: str) -> Response | None:
    """Serve files from /static/<path> and /apps/<id>/static/<path>."""
    candidates: list[tuple[str, str]] = []
    if path.startswith("/static/"):
        candidates.append((_static_dir, path[len("/static/") :]))
    elif path.startswith("/apps/"):
        rest = path[len("/apps/") :]
        app_id, _, rest = rest.partition("/")
        if rest.startswith("static/") and app_id in app_static_dirs:
            candidates.append((app_static_dirs[app_id], rest[len("static/") :]))
    for root, rel in candidates:
        if not rel or ".." in rel.split("/"):
            return Response("Invalid path", status=400)
        full = os.path.normpath(os.path.join(root, rel))
        if not full.startswith(os.path.normpath(root)):
            return Response("Invalid path", status=400)
        if not os.path.isfile(full):
            return None
        try:
            return send_file(full)
        except OSError:
            return None
    return None


app_static_dirs: dict[str, str] = {}


def save_config():
    os.makedirs(config_dir, exist_ok=True)
    with open(data_path, "wb") as cfw:
        pickle.dump(config, cfw)


if os.path.exists(data_path):
    with open(data_path, "rb") as cfr:
        config = pickle.load(cfr)
else:
    config = {}

# Determine whether to show command output
show_output = logger.isEnabledFor(logging.DEBUG)

# App stuff


## Settings
class Setting:
    """
    A setting is a configuration option for an app. Do not call this directly.
    """

    def __init__(
        self, id: str, display_name: str, default: Any, type: str, hidden: bool = False
    ):
        self.id = id
        self.display_name = display_name
        self.default = default
        self.hidden = hidden
        self.type = type
        self.app: App | None = None

    def get_value(self):
        if self.app is None:
            raise ValueError("Setting must be added to an app")
        return config[self.app.id][self.id]

    def set_value(self, value: Any, persist: bool = True):
        if self.app is None:
            raise ValueError("Setting must be added to an app before setting a value")
        config[self.app.id][self.id] = value
        if persist:
            save_config()


class StringSetting(Setting):
    def __init__(self, id: str, display_name: str, default: str, hidden: bool = False):
        super().__init__(id, display_name, default, "string", hidden)


class BooleanSetting(Setting):
    def __init__(self, id: str, display_name: str, default: bool, hidden: bool = False):
        super().__init__(id, display_name, default, "bool", hidden)


class FloatSetting(Setting):
    def __init__(
        self,
        id: str,
        display_name: str,
        default: float,
        hidden: bool = False,
        min_value: float | None = None,
        max_value: float | None = None,
        unit: str | None = None,
    ):
        super().__init__(id, display_name, default, "float", hidden)
        self.min_value = min_value
        self.max_value = max_value
        self.unit = unit


class IntegerSetting(Setting):
    def __init__(
        self,
        id: str,
        display_name: str,
        default: int,
        hidden: bool = False,
        min_value: int | None = None,
        max_value: int | None = None,
        unit: str | None = None,
    ):
        super().__init__(id, display_name, default, "int", hidden)
        self.min_value = min_value
        self.max_value = max_value
        self.unit = unit


class SelectSetting(Setting):
    def __init__(
        self,
        id: str,
        display_name: str,
        default: str,
        options: dict[str, str],
        hidden: bool = False,
    ):
        super().__init__(id, display_name, default, "select", hidden)
        self.options = options


class DataSetting(Setting):
    def __init__(self, id: str, default: Any):
        super().__init__(id, "", default, "data", True)


class ElementSetting:
    def __init__(self, id: str, type: str, hidden: bool = False):
        self.type = type
        self.id = id
        self.hidden = hidden

    def get_value(self):
        raise NotImplementedError(
            "ElementSettings cannot store data, but get_value was called."
        )

    def set_value(self, value: Any):
        raise NotImplementedError(
            "ElementSettings cannot store data, but set_value was called."
        )


class LinkSetting(ElementSetting):
    def __init__(self, id: str, label: str, link: str, hidden: bool = False):
        super().__init__(id, "link", hidden)
        self.label = label
        self.link = link


class LabelSetting(ElementSetting):
    def __init__(self, id: str, label: str, hidden: bool = False):
        super().__init__(id, "label", hidden)
        self.label = label


## Apps

broadcast_listeners: dict[str, list[Callable]] = {}
READABLE_CATEGORIES = {
    "core": "Core",
    "musicprovider": "Music Providers",
    "device": "Devices",
    "music": "Music",
    "system": "System",
    "uncategorized": "Uncategorized",
}


class App:
    # TODO: docstring these functions to make it easier to build apps
    """
    Represents a pything app, use this class to create your app, and specify settings
    """

    def __init__(
        self,
        settings: list[Setting | ElementSetting],
    ):
        stack = inspect.stack()
        self.dir = os.path.dirname(os.path.abspath(stack[1].filename))
        self.dirname = os.path.basename(self.dir)
        manifest_path = os.path.join(self.dir, "manifest.json")
        try:
            with open(manifest_path, encoding="utf-8") as manifest_file:
                manifest = json.load(manifest_file)
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"Failed to load manifest for app directory '{self.dir}'"
            ) from exc
        required_manifest_fields = {"id", "name", "codeowners", "category"}
        if not isinstance(manifest, dict) or not required_manifest_fields.issubset(
            manifest
        ):
            if not isinstance(manifest, dict):
                missing_fields = required_manifest_fields
            else:
                missing_fields = required_manifest_fields - manifest.keys()
            raise RuntimeError(
                f"Manifest for app directory '{self.dir}' is missing: "
                + ", ".join(sorted(missing_fields))
            )
        if not all(
            isinstance(manifest[field], str) for field in ("id", "name", "category")
        ):
            raise RuntimeError(
                f"Manifest for app directory '{self.dir}' has invalid metadata"
            )
        self.id = manifest["id"]
        self.display_name = manifest["name"]
        self.category = manifest["category"]
        apps[self.id] = self
        self.logger = logging.getLogger("pything.app." + self.id)
        logger.debug(
            f"Logger initialized for '{self.display_name}' with id '{self.id}'"
        )
        self.blueprint = Blueprint(
            self.id,
            __name__,
            static_folder=os.path.abspath(self.dir) + "/static"
            if os.path.isdir(os.path.join(self.dir, "static"))
            else None,
        )
        if self.blueprint.static_folder:
            app_static_dirs[self.id] = self.blueprint.static_folder

        self.settings = {s.id: s for s in settings}
        self.hidden = True  # updated on init
        self.listeners = {}
        self.startup_listeners: list[Callable] = []
        self.settingupdatelisteners: list[Callable] = []
        if not self.id in config:
            config[self.id] = {}
        schange = False
        for setting in settings:
            if not isinstance(setting, Setting):
                if isinstance(setting, ElementSetting):
                    continue
                raise ValueError(
                    "Settings must be instances of the Setting or ElementSetting class"
                )
            setting.app = self
            if not setting.id in config[self.id]:
                schange = True
                logger.debug(
                    f"Setting {setting.id} for {self.id} to default of {setting.default!s}"
                )
                config[self.id][setting.id] = setting.default
        if schange:
            logger.debug("Saving config with new default settings")
            save_config()

    def should_poll(self) -> bool:
        """
        Checks if at least one client has the App open
        """
        for client in clients.values():
            if client.app == self.id:
                return True
        return False

    def get_open_clients(self) -> Generator:
        for client in clients.values():
            if client.app == self.id:
                yield client

    def on(self, event: str):
        def decorator(func):
            self.listeners[event] = func
            return func

        return decorator

    def send(self, event: str, data, to: set[str] | str | None = None):
        logger.debug("serverapp>clientapp: %s > %s", self.id, event)
        if isinstance(to, set):
            for c in self.get_open_clients():
                if c.sid in to:
                    socket.emit("app_com", [self.id, event, data], to=c.sid)
            return
        if isinstance(to, str):
            for c in self.get_open_clients():
                if c.sid == to:
                    socket.emit("app_com", [self.id, event, data], to=c.sid)
            return
        for c in self.get_open_clients():
            socket.emit("app_com", [self.id, event, data], to=c.sid)

    def on_startup(self, func: Callable):
        self.startup_listeners.append(func)
        return func

    def startup(self):
        for listener in self.startup_listeners:
            self.logger.debug("Calling startup listener %s", listener.__name__)
            listener()

    def on_broadcast(self, event: str):
        def decorator(func):
            if event not in broadcast_listeners:
                broadcast_listeners[event] = []
            broadcast_listeners[event].append(func)
            return func

        return decorator

    def broadcast(self, event: str, *args, **kwargs):
        if event not in broadcast_listeners:
            self.logger.debug(
                "A broadcast to %s was sent by %s, but that event has no listeners, you can probably ignore this",
                event,
                self.id,
            )
            return
        for listener in broadcast_listeners[event]:
            listener(*args, **kwargs)
        self.logger.debug(
            "Broadcasting event %s to %d listeners",
            event,
            len(broadcast_listeners[event]),
        )

    def on_setting_update(self, func: Callable):
        self.logger.debug("Adding setting update listener %s", func.__name__)
        self.settingupdatelisteners.append(func)
        return func


apps: dict[str, App] = {}


def get_apps():
    return apps


# Client tracking
clients: dict[str, "Client"] = {}


class Client:
    def __init__(self, sid: str, conn: "WSConnection") -> None:
        self.sid = sid
        self.conn = conn
        self.app = "dashboard"
        clients[sid] = self

    def change_app(self, app: App | str):
        if isinstance(app, App):
            app = app.id
        if not isinstance(app, str):
            raise TypeError("Argument app must be a string with the ID of the app")
        self.app = app
        socket.emit("changeframe", "/apps/" + app + "/launch", to=self.sid)


# ---------------------------------------------------------------------------
# Raw WebSocket transport (RFC 6455) — replaces flask-socketio
# ---------------------------------------------------------------------------

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
            targets = list(clients.values())
        else:
            target = clients.get(to)
            targets = [target] if target else []
        for client in targets:
            try:
                client.conn.send_json({"event": event, "args": list(args)})
            except (OSError, ConnectionError):
                logger.debug("Could not send %s to client %s", event, client.sid)


socket = Socket()


def _handle_ws_message(client: Client, event: str, args: list) -> None:
    req = _get_request()
    req.sid = client.sid
    req.args = MultiDict({})
    req.form = MultiDict({})
    handler = socket._handlers.get(event)
    if handler is not None:
        logger.debug("WS %s <- %s %r", client.sid, event, args)
        handler(*args)
        return
    # Built-in events (formerly @socket.on handlers in this module)
    if event == "open_app":
        logger.debug("%s is opening %s", client.sid, args[0])
        client.change_app(args[0])
    elif event == "app_com":
        app_id, app_event, data = args
        if app_id not in apps:
            logger.error("A client just sent a request to non-existent app '%s'", app_id)
            return
        if app_event == "debug":
            logger.debug("Client debug message to %s: %s", app_id, data)
            return
        if app_event not in apps[app_id].listeners:
            logger.warning(
                "A client just sent a message to '%s' with non-existent event '%s'",
                app_id,
                app_event,
            )
            return
        apps[app_id].listeners[app_event](data)
    elif event == "debug":
        logger.debug("Client message: %s", args[0] if args else "")


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
                logger.warning("Ignoring invalid websocket message from %s", client.sid)
                continue
            args = message.get("args", [])
            if not isinstance(args, list):
                args = [args]
            _handle_ws_message(client, message.get("event", ""), args)
    finally:
        clients.pop(client.sid, None)
        client.conn.close()
        logger.debug("Client %s disconnected", client.sid)


# ---------------------------------------------------------------------------
# HTTP server (stdlib http.server) — replaces Flask
# ---------------------------------------------------------------------------


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "PYThing/1.0"

    def log_message(self, format, *args):
        logger.debug("%s - %s", self.address_string(), format % args)

    # -- websocket upgrade ------------------------------------------------
    def _is_websocket_upgrade(self) -> bool:
        return (
            self.headers.get("Upgrade", "").lower() == "websocket"
            and self.headers.get("Connection", "").lower().find("upgrade") != -1
        )

    def _do_websocket(self) -> None:
        key = self.headers.get("Sec-WebSocket-Key", "")
        rfile = self.rfile
        wfile = self.wfile
        handshake = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {_ws_accept_key(key)}\r\n"
            "\r\n"
        )
        wfile.write(handshake.encode())
        wfile.flush()
        sid = os.urandom(12).hex()
        conn = WSConnection(rfile, wfile)
        client = Client(sid, conn)
        logger.debug("Client %s connected", sid)
        # Push server time immediately, like the old connect handler did.
        conn.send_json(
            {"event": "dt", "args": [datetime.datetime.now().isoformat()]}
        )
        _run_ws_connection(rfile, wfile, client)

    # -- normal HTTP --------------------------------------------------------
    def _handle(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)
        req = _get_request()
        req.args = MultiDict(urllib.parse.parse_qs(parsed.query, keep_blank_values=True))
        req.form = MultiDict({})
        req.sid = None
        _set_current_app(None)

        if self.command == "POST":
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            req.form = MultiDict(
                urllib.parse.parse_qs(body.decode(errors="replace"), keep_blank_values=True)
            )

        response = _dispatch(self.command, path)
        if response is None:
            response = _serve_static(path)
        if response is None:
            response = Response("Not found", status=404)
        self._send_response(response)

    def _send_response(self, response: Response) -> None:
        self.send_response(response.status)
        self.send_header("Content-Type", response.content_type)
        self.send_header("Content-Length", str(len(response.body)))
        for key, value in response.headers.items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD" and response.body:
            self.wfile.write(response.body)

    def do_GET(self):
        if self._is_websocket_upgrade() and urllib.parse.urlparse(self.path).path == "/ws":
            self._do_websocket()
            return
        self._handle()

    def do_POST(self):
        self._handle()

    def do_HEAD(self):
        self._handle()


# Utilities

client_mods: list[tuple[str, App]] = []
app_mods: list[tuple[str, App]] = []


# Built in routes


@route("/isready")
def ct_isready():
    return Response("OK", headers={"Access-Control-Allow-Origin": "*"})


@route("/")
def client_redirect():
    return redirect("/client")


@route("/client")
def main_client():
    _set_current_app(None)
    return render_template("client.html", mods=client_mods)


@route("/settings")
def settings_editor():
    # sort and hide apps with no visible settings, beware of ai slop
    sapps: dict[str, list[App]] = {}
    for app in apps.values():
        if not any(not s.hidden for s in app.settings.values()):
            continue
        if not app.category in sapps:
            sapps[app.category] = []
        sapps[app.category].append(app)
    sapps = {
        category: sorted(category_apps, key=lambda a: a.display_name)
        for category, category_apps in sorted(
            sapps.items(),
            key=lambda item: (item[0] == "uncategorized", item[0].casefold()),
        )
    }
    # end ai
    return render_template(
        "settings.html",
        apps=sapps,
        readable_categories=READABLE_CATEGORIES,
        custom_hue=config.get("customizer", {}).get("hue", 151),
    )


def app_manifest(app_dir: str) -> dict[str, Any]:
    with open(
        os.path.join(app_dir, "manifest.json"), encoding="utf-8"
    ) as manifest_file:
        manifest = json.load(manifest_file)
    if not isinstance(manifest, dict):
        raise TypeError(f"Manifest for app directory '{app_dir}' must be an object")
    dependencies = manifest.get("dependencies", {})
    if not isinstance(dependencies, dict):
        raise RuntimeError(  # noqa: TRY004
            f"Manifest for app directory '{app_dir}' has invalid dependencies"
        )
    for dependency_type in ("required", "optional"):
        values = dependencies.setdefault(dependency_type, [])
        if not isinstance(values, list) or not all(
            isinstance(value, str) for value in values
        ):
            raise RuntimeError(
                f"Manifest for app directory '{app_dir}' has invalid {dependency_type} dependencies"
            )
    manifest["dependencies"] = dependencies
    return manifest


def discover_apps() -> dict[str, dict[str, Any]]:
    discovered: dict[str, dict[str, Any]] = {}
    for app_root in ("apps", "customapps"):
        if not os.path.isdir(app_root):
            continue
        for app_name in sorted(os.listdir(app_root)):
            app_dir = os.path.join(app_root, app_name)
            if not os.path.isdir(app_dir) or not os.path.isfile(
                os.path.join(app_dir, "manifest.json")
            ):
                continue
            manifest = app_manifest(app_dir)
            app_id = manifest.get("id")
            if not isinstance(app_id, str):
                raise TypeError(
                    f"Manifest for app directory '{app_dir}' has invalid id"
                )
            if app_id in discovered:
                raise RuntimeError(
                    f"App id '{app_id}' is defined more than once"
                )  # TODO: disable duplicate apps when we allow custom apps
            discovered[app_id] = {
                "id": app_id,
                "name": manifest.get("name", app_id),
                "description": manifest.get("description", ""),
                "core": manifest.get("core", False),
                "default": manifest.get("default", False),
                "category": manifest.get("category", "uncategorized"),
                "dependencies": manifest["dependencies"],
                "directory": app_dir,
            }
    return discovered


def required_dependency_closure(
    selected: set[str], manifests: dict[str, dict[str, Any]]
) -> set[str]:
    enabled = selected & set(manifests)
    changed = True
    while changed:
        changed = False
        for app_id in tuple(enabled):
            for dependency in manifests[app_id]["dependencies"]["required"]:
                if dependency not in manifests:
                    enabled.remove(app_id)
                    changed = True
                    break
                if dependency not in enabled:
                    enabled.add(dependency)
                    changed = True
    return enabled


def enabled_apps(manifests: dict[str, dict[str, Any]]) -> set[str]:
    # Apply manifest defaults on first start and only to newly discovered apps later.
    default_apps = {
        app_id
        for app_id, manifest in manifests.items()
        if manifest.get("default") is True or manifest["core"]
    }

    # Save the initial selection and installed IDs for future update checks.
    if APP_CONFIG_ID not in config:
        initially_enabled = required_dependency_closure(default_apps, manifests)
        config[APP_CONFIG_ID] = {
            "disabled": sorted(set(manifests) - initially_enabled),
            "known": sorted(manifests),
        }
        save_config()
    else:
        app_config = config[APP_CONFIG_ID]
        if "known" not in app_config:
            # Preserve existing choices when upgrading from configs created before
            # app IDs were tracked.
            app_config["known"] = sorted(manifests)
            save_config()
        else:
            known_apps = set(app_config["known"])
            # Apply defaults only to apps added since the last saved selection.
            new_apps = set(manifests) - known_apps
            if new_apps:
                disabled = set(app_config.get("disabled", []))
                disabled.update(new_apps - default_apps)
                disabled.difference_update(new_apps & default_apps)
                app_config["disabled"] = sorted(disabled)
            if known_apps != set(manifests):
                app_config["known"] = sorted(manifests)
                save_config()

    disabled = set(config.get(APP_CONFIG_ID, {}).get("disabled", []))
    core_apps = {app_id for app_id, manifest in manifests.items() if manifest["core"]}
    return required_dependency_closure(set(manifests) - disabled | core_apps, manifests)


def app_dependency_view(manifests: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    enabled = enabled_apps(manifests)
    app_names = {app_id: manifest["name"] for app_id, manifest in manifests.items()}
    required_by: dict[str, set[str]] = {app_id: set() for app_id in manifests}
    for app_id, manifest in manifests.items():
        for dependency in manifest["dependencies"]["required"]:
            if dependency in required_by and app_id in enabled:
                required_by[dependency].add(app_id)
    result = []
    for app_id in sorted(
        manifests,
        key=lambda item: (manifests[item]["core"], manifests[item]["name"].casefold()),
    ):
        manifest = manifests[app_id]
        missing_required = [
            dependency
            for dependency in manifest["dependencies"]["required"]
            if dependency not in manifests
        ]
        result.append(
            {
                **manifest,
                "enabled": app_id in enabled,
                "required_names": [
                    app_names.get(dependency, dependency)
                    for dependency in manifest["dependencies"]["required"]
                ],
                "optional_names": [
                    app_names.get(dependency, dependency)
                    for dependency in manifest["dependencies"]["optional"]
                ],
                "required_by_names": [
                    app_names.get(dependency, dependency)
                    for dependency in sorted(required_by[app_id])
                ],
                "missing_required": missing_required,
                "missing_required_names": [
                    app_names.get(dependency, dependency)
                    for dependency in missing_required
                ],
            }
        )
    return result


@route("/apps", methods=("GET",))
def apps_editor():
    manifests = discover_apps()
    return render_template(
        "apps.html",
        installed_apps=app_dependency_view(manifests),
        custom_hue=config.get("customizer", {}).get("hue", 151),
    )


@route("/apps", methods=("POST",))
def apps_set():
    manifests = discover_apps()
    selected = {app_id for app_id in manifests if f"app-{app_id}" in request.form}
    selected.update(
        app_id for app_id, manifest in manifests.items() if manifest["core"]
    )
    enabled = required_dependency_closure(selected, manifests)
    config[APP_CONFIG_ID] = {"disabled": sorted(set(manifests) - enabled)}
    save_config()

    def restart() -> None:
        os._exit(RESTART_EXIT_CODE)

    threading.Timer(0.5, restart).start()
    return (
        "<style>html { background: linear-gradient(350deg, #272727, #1f1f1f); color:"
        " #fff; }</style><h1 id='restarting'>PYThing is restarting...</h1><script>const params = new"
        " URLSearchParams(window.location.search); if (!params.has('from')) {"
        " setInterval(() => { fetch('/apps').then(response =>"
        " response.text()).then(data => { window.location.href = '/settings'; }); },"
        " 1000); } else { document.getElementById('restarting').style.textAlign = 'center'; document.getElementById('restarting').style.lineHeight = '99vh'; } </script>"
    )


@route("/settings", methods=("POST",))
def settings_set():
    logger.debug("Got new settings: %s", request.form)
    settings_changed = False
    for app in apps.values():
        changed: dict[str, Any] = {}
        for setting in app.settings.values():
            if f"{app.id}-{setting.id}" in request.form:
                nd = request.form[f"{app.id}-{setting.id}"]
                logger.debug(f"Setting '{app.id}' > '{setting.id}' to {nd!s}")
                match setting.type:
                    case "bool":
                        nd = nd == "on"
                    case "int":
                        nd = int(nd)
                        if setting.min_value is not None and nd < setting.min_value:
                            raise ValueError(
                                f"Value for int setting '{setting.id}' is below minimum of {setting.min_value}"
                            )
                        if setting.max_value is not None and nd > setting.max_value:
                            raise ValueError(
                                f"Value for int setting '{setting.id}' is above maximum of {setting.max_value}"
                            )
                    case "float":
                        nd = float(nd)
                        if setting.min_value is not None and nd < setting.min_value:
                            raise ValueError(
                                f"Value for float setting '{setting.id}' is below minimum of {setting.min_value}"
                            )
                        if setting.max_value is not None and nd > setting.max_value:
                            raise ValueError(
                                f"Value for float setting '{setting.id}' is above maximum of {setting.max_value}"
                            )
                    case "select":
                        if nd not in setting.options:
                            raise ValueError(
                                f"Invalid value for select setting '{setting.id}'"
                            )
                logger.debug(f"Setting as {nd}")
                if setting.get_value() != nd:
                    changed[setting.id] = nd
                    setting.set_value(nd, persist=False)
                    settings_changed = True
        if changed:
            for sl in app.settingupdatelisteners:
                sl(changed)
    if settings_changed:
        save_config()
    return redirect("/settings")


# Background updates
def clock_thread():
    while True:
        socket.emit("dt", datetime.datetime.now().isoformat())
        time.sleep(60)


def import_app(iappd: str):
    if not os.path.isdir(iappd):
        raise RuntimeError(
            "All apps must be directories, name your app as <name>/__init__.py"
        )
    logger.debug("Importing app %s", iappd)
    start_time = time.time()
    iapp = importlib.import_module(iappd.replace(os.sep, "."))
    end_time = time.time()
    logger.debug("Imported app %s in %.3f seconds", iappd, end_time - start_time)
    if not hasattr(iapp, "app"):
        raise RuntimeError(f"App {iappd} does not have an 'app' variable")
    # isinstance does not work for some reason, so we check for attributes
    if not (
        hasattr(iapp.app, "id")
        and hasattr(iapp.app, "blueprint")
        and hasattr(iapp.app, "display_name")
    ):
        raise TypeError(
            f"App {iappd} variable 'app' does not appear to be a valid App instance ({type(iapp.app)!s})"
        )
    # Make sure the blueprint is valid
    if not isinstance(iapp.app.blueprint, Blueprint):
        raise TypeError(
            f"App {iappd} variable 'app' has invalid blueprint ({type(iapp.app.blueprint)!s})"
        )
    _register_blueprint_routes(
        iapp.app.blueprint, "/apps/" + iapp.app.id, iapp.app.id
    )
    if os.path.exists(os.path.join(iappd, "clientmod.html")):
        client_mods.append(
            (os.path.join(iapp.app.id, "clientmod.html").replace("\\", "/"), iapp.app)
        )
    if os.path.exists(os.path.join(iappd, "appmod.html")):
        app_mods.append(
            (os.path.join(iapp.app.id, "appmod.html").replace("\\", "/"), iapp.app)
        )
    for _methods, regex, _conv, _handler, app_id in _routes:
        if app_id == iapp.app.id and regex.pattern == "^/apps/" + iapp.app.id + "/launch$":
            logger.debug("%s has a launch route", iapp.app.id)
            iapp.app.hidden = False
            break


def main() -> None:
    print("Starting PYThing...")
    global apps
    logger.debug("Init apps...")

    # Load enabled apps
    manifests = discover_apps()
    enabled = sorted(enabled_apps(manifests))
    install_app_requirements(manifests[app_id]["directory"] for app_id in enabled)
    for app_id in enabled:
        import_app(manifests[app_id]["directory"])

    # Sort apps dict
    apps = dict(sorted(apps.items()))

    for loaded_app in apps.values():
        loaded_app.startup()

    # Start clock thread
    threading.Thread(target=clock_thread, daemon=True).start()

    # Start the server
    logger.info("Starting on %s:%s", HOST, PORT)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.daemon_threads = True
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
