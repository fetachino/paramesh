"""Read-only operator HTTP surface; service credentials never reach the browser."""

import json
import re
import socket
import threading
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast
from urllib.error import URLError
from urllib.parse import parse_qs, urlsplit

from paramesh.monitor import ClusterView
from paramesh.operations import Sessions

WEB = Path(__file__).with_name("web")
ASSETS = {
    "/assets/app.js": ("app.js", "text/javascript"),
    "/assets/style.css": ("style.css", "text/css"),
    "/assets/favicon.svg": ("favicon.svg", "image/svg+xml"),
}
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; frame-ancestors 'none'; object-src 'none'; "
    "base-uri 'none'; form-action 'self'"
)


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 16

    def __init__(
        self,
        address: tuple[str, int],
        view: ClusterView,
        password: str,
        *,
        secure_cookie: bool = False,
    ) -> None:
        self.view, self.sessions, self.secure_cookie = view, Sessions(password), secure_cookie
        self.slots = threading.BoundedSemaphore(16)
        super().__init__(address, Handler)

    def get_request(self) -> tuple[socket.socket, Any]:
        request, address = super().get_request()
        request.settimeout(5)
        return request, address

    def process_request(self, request: Any, client_address: Any) -> None:
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


class Handler(BaseHTTPRequestHandler):
    server_version = "ParamMesh"
    sys_version = ""

    @property
    def app(self) -> DashboardServer:
        return cast(DashboardServer, self.server)

    def log_message(self, format: str, *args: Any) -> None:
        # Request paths and headers can contain supplied credentials; never echo them.
        pass

    def _send(
        self,
        status: int,
        payload: bytes = b"",
        content_type: str = "application/json",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.send_response(status)
        for name, value in {
            "Content-Type": content_type,
            "Content-Length": str(len(payload)),
            "Cache-Control": "no-store",
            "Content-Security-Policy": CSP,
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "same-origin",
            **(headers or {}),
        }.items():
            self.send_header(name, value)
        self.end_headers()
        try:
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, status: int, data: Any) -> None:
        self._send(status, json.dumps(data, allow_nan=False).encode())

    def _authorized(self) -> bool:
        raw = self.headers.get("Cookie", "")
        if len(raw) > 4096:
            return False
        try:
            cookies = SimpleCookie(raw)
        except CookieError:
            return False
        token = cookies.get("paramesh_session")
        return self.app.sessions.valid(token.value) if token else False

    def _login(self, status: int = 200) -> None:
        error = "Invalid credentials." if status == 401 else ""
        page = (
            '<!doctype html><html lang="en"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            "<title>ParamMesh · Operator sign in</title>"
            '<link rel="icon" href="/assets/favicon.svg">'
            '<link rel="stylesheet" href="/assets/style.css">'
            '<body class="login-page"><main class="login-panel"><div class="wordmark">'
            '<span class="logo-mark" aria-hidden="true">P</span> ParamMesh</div>'
            '<p class="eyebrow">DISTRIBUTED TRAINING OPERATIONS</p><h1>Operator sign in</h1>'
            '<p class="muted">Inspect the training cluster, recovery history and telemetry.</p>'
            '<form action="/login" method="post"><label for="username">Username</label>'
            '<input id="username" name="username" value="operator" '
            'autocomplete="username" required>'
            '<label for="password">Password</label><input id="password" name="password" '
            'type="password" autocomplete="current-password" maxlength="256" required>'
            '<button type="submit" class="primary-button">Sign in</button></form>'
            f'<p class="login-error" role="status">{error}</p></main></body></html>'
        )
        self._send(status, page.encode(), "text/html; charset=utf-8")

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == "/healthz":
            self._json(200, {"ready": True})
            return
        if path == "/login":
            self._login()
            return
        if path in ASSETS:
            name, mime = ASSETS[path]
            self._send(200, (WEB / name).read_bytes(), mime)
            return
        if not self._authorized():
            if path.startswith("/api/"):
                self._json(401, {"error": "authentication_required"})
            else:
                self._send(303, headers={"Location": "/login"})
            return
        try:
            if path == "/":
                self._send(200, (WEB / "index.html").read_bytes(), "text/html; charset=utf-8")
            elif path == "/api/state":
                self._json(200, self.app.view.snapshot())
            elif path == "/api/benchmarks":
                self._json(200, self.app.view.benchmarks())
            elif re.fullmatch(r"/api/trace/[a-f0-9]{32}", path):
                self._json(200, self.app.view.trace(path.rsplit("/", 1)[-1]))
            else:
                self._json(404, {"error": "not_found"})
        except (URLError, OSError, ValueError):
            self._json(503, {"error": "backend_unavailable"})

    def do_POST(self) -> None:
        origin = self.headers.get("Origin")
        host = self.headers.get("Host")
        if origin and origin not in (f"http://{host}", f"https://{host}"):
            self._json(403, {"error": "origin_rejected"})
            return
        path = urlsplit(self.path).path
        if path == "/logout" and self._authorized():
            self.app.sessions.logout()
            self._send(
                303,
                headers={
                    "Location": "/login",
                    "Set-Cookie": "paramesh_session=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict",
                },
            )
            return
        if path != "/login":
            self._json(404, {"error": "not_found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 <= length <= 4096:
                self._json(413, {"error": "request_too_large"})
                return
            fields = parse_qs(
                self.rfile.read(length).decode(), strict_parsing=True, max_num_fields=2
            )
            if fields.keys() != {"username", "password"} or any(
                len(value) != 1 for value in fields.values()
            ):
                raise ValueError("Invalid login fields")
        except (ValueError, UnicodeError):
            self._json(400, {"error": "invalid_request"})
            return
        token = self.app.sessions.login(fields["username"][0], fields["password"][0])
        if token is None:
            self._login(401)
            return
        cookie = f"paramesh_session={token}; Path=/; Max-Age=28800; HttpOnly; SameSite=Strict"
        if self.app.secure_cookie:
            cookie += "; Secure"
        self._send(303, headers={"Location": "/", "Set-Cookie": cookie})
