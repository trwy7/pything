"""HTTP server wiring: the request handler that dispatches to routes."""

from __future__ import annotations

import datetime
import os
import urllib.parse
from http.server import BaseHTTPRequestHandler

from . import state
from .web import (
    MultiDict,
    Response,
    _dispatch,
    _get_request,
    _serve_static,
    _set_current_app,
)
from .websocket import (
    Client,
    WSConnection,
    _run_settings_ws_connection,
    _run_ws_connection,
    _ws_accept_key,
)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "PYThing/1.0"

    def log_message(self, format, *args):
        state.logger.debug("%s - %s", self.address_string(), format % args)

    # -- websocket upgrade ------------------------------------------------
    def _is_websocket_upgrade(self) -> bool:
        return (
            self.headers.get("Upgrade", "").lower() == "websocket"
            and self.headers.get("Connection", "").lower().find("upgrade") != -1
        )

    def _do_websocket(self, settings: bool = False) -> None:
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
        conn = WSConnection(rfile, wfile)
        if settings:
            _run_settings_ws_connection(conn)
            return
        sid = os.urandom(12).hex()
        client = Client(sid, conn)
        state.logger.debug("Client %s connected", sid)
        # Push server time immediately, like the old connect handler did.
        conn.send_json({"event": "dt", "args": [datetime.datetime.now().isoformat()]})
        _run_ws_connection(rfile, wfile, client)

    # -- normal HTTP --------------------------------------------------------
    def _handle(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)
        req = _get_request()
        req.args = MultiDict(
            urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        )
        req.form = MultiDict({})
        req.sid = None
        _set_current_app(None)

        if self.command == "POST":
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            req.form = MultiDict(
                urllib.parse.parse_qs(
                    body.decode(errors="replace"), keep_blank_values=True
                )
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
        if self._is_websocket_upgrade():
            path = urllib.parse.urlparse(self.path).path
            if path == "/ws":
                self._do_websocket()
                return
            if path == "/settings/ws":
                self._do_websocket(settings=True)
                return
        self._handle()

    def do_POST(self):
        self._handle()

    def do_HEAD(self):
        self._handle()
