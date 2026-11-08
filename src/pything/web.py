"""HTTP layer: responses, requests, routing, static files and templates."""

from __future__ import annotations

import mimetypes
import os
import re
import threading
from collections.abc import Callable
from typing import Any

from . import state

logger = state.logger  # alias so logging calls match the original module


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


def _get_current_app() -> Any | None:
    return getattr(_local, "current_app", None)


def _set_current_app(app: Any | None) -> None:
    _local.current_app = app


class _RequestProxy:
    """Thread-local proxy so ``request`` always reflects the active request."""

    def __getattr__(self, name: str) -> Any:
        return getattr(_get_request(), name)


request = _RequestProxy()

# Templates that include per-app mod fragments (clientmod/appmod) are rendered
# once per owning app so each fragment sees its own ``app``. The pre-rendered
# HTML is injected as ``mods_html`` / ``app_mods_html``.


def _render_template(name: str, **ctx: Any) -> str:
    ctx.setdefault("apps", state.apps)
    ctx.setdefault("app_mods", state.app_mods)
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
    return state.jinja_env.get_template(name).render(**ctx)


def render_template(name: str, **ctx: Any) -> Response:
    return Response(_render_template(name, **ctx))


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


def _compile_route(path: str) -> tuple[re.Pattern, dict[str, Callable]]:
    converters: dict[str, Callable] = {}

    def repl(match: re.Match) -> str:
        kind, name = match.group(1), match.group(2)
        pattern, conv = _converters.get(kind, ("[^/]+", str))
        converters[name] = conv
        return f"(?P<{name}>{pattern})"

    regex = re.sub(r"<(?:(\w+):)?(\w+)>", repl, path)
    return re.compile("^" + regex + "$"), converters


def route(path: str, methods: tuple[str, ...] = ("GET",)):
    def decorator(func: Callable) -> Callable:
        regex, converters = _compile_route(path)
        state.routes.append((set(methods), regex, converters, func, None))
        return func

    return decorator


def _register_blueprint_routes(blueprint: Blueprint, prefix: str, app_id: str) -> None:
    for path, methods, func in blueprint._routes:
        regex, converters = _compile_route(prefix + path)
        state.routes.append((set(methods), regex, converters, func, app_id))


def _dispatch(method: str, path: str) -> Response | None:
    """Match a request against registered routes. Returns None if no match."""
    for methods, regex, converters, handler, app_id in state.routes:
        if method not in methods:
            continue
        match = regex.match(path)
        if not match:
            continue
        kwargs = {
            name: converters[name](value) for name, value in match.groupdict().items()
        }
        if app_id is not None and app_id in state.apps:
            _set_current_app(state.apps[app_id])
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


_static_dir = os.path.join(state.base_dir, "static")


def _serve_static(path: str) -> Response | None:
    """Serve files from /static/<path> and /apps/<id>/static/<path>."""
    candidates: list[tuple[str, str]] = []
    if path.startswith("/static/"):
        candidates.append((_static_dir, path[len("/static/") :]))
    elif path.startswith("/apps/"):
        rest = path[len("/apps/") :]
        app_id, _, rest = rest.partition("/")
        if rest.startswith("static/") and app_id in state.app_static_dirs:
            candidates.append((state.app_static_dirs[app_id], rest[len("static/") :]))
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
