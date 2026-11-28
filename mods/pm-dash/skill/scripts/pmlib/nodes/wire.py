"""The two carriers of the self-hosted sync protocol (MR-D2), the same JSON on both. Layer 3 (nodes).

Coordinator side:
- `serve_stdio(hub, stdin, write)`: `pm.py mailbox-sync --stdio`, for a restricted SSH command (`command="..."` in
  `authorized_keys`): one JSON request per line in, one JSON reply per line out, until EOF.
- `wsgi_app(hub)`: `POST /v1/worker/sync` as a WSGI callable a resident service can mount as it is.
- `serve_http(hub, host, port)`: the same over the standard library's `ThreadingHTTPServer` (`pm.py worker-hub`;
  put TLS in front of it, or bind it to loopback behind a tunnel).

Node side, `call(request) -> reply`, raising `HubUnavailable` when the hub cannot be reached (the agent keeps
everything buffered and backs off):
- `HttpHubClient(url)`; `StdioHubClient(argv)` (`ssh <host> pm.py mailbox-sync --stdio`); `InProcessHubClient`.
"""
from __future__ import annotations

import json
import subprocess
from typing import Any, Callable, Iterable, Mapping, Sequence

from ..messaging.nodes import MAX_SYNC_BYTES
from .hub import SyncHub, error_reply, http_status_of


SYNC_PATHS = ("/v1/worker/sync", "/v1/worker/join")
DEFAULT_TIMEOUT_S = 60.0
HTTP_REASONS = {200: "OK", 400: "Bad Request", 401: "Unauthorized", 403: "Forbidden", 404: "Not Found",
                405: "Method Not Allowed", 413: "Payload Too Large"}


class HubUnavailable(Exception):
    """The hub did not answer (network down, SSH failed, timeout): nothing was concluded."""


def _reply_of(raw: bytes | str) -> dict[str, Any]:
    text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
    try:
        reply = json.loads(text)
    except ValueError as err:
        raise HubUnavailable(f"unreadable reply from the hub: {text[:200]!r}") from err
    if not isinstance(reply, dict):
        raise HubUnavailable("the hub's reply is not a JSON object")
    return reply


# --- coordinator side -------------------------------------------------------------------------------------------


def serve_stdio(hub: SyncHub, stdin: Iterable[str], write: Callable[[str], None]) -> int:
    """Answer each request line; returns how many were answered."""
    n = 0
    for line in stdin:
        if not line.strip():
            continue
        write(hub.handle_bytes(line.strip()).decode("utf-8"))
        n += 1
    return n


def handle_http(hub: SyncHub, method: str, path: str, body: bytes) -> tuple[int, bytes]:
    """`(status, reply bytes)` for one HTTP request: what the WSGI app and the server share."""
    if path.split("?", 1)[0] not in SYNC_PATHS:
        return 404, json.dumps(error_reply("not_found", "POST /v1/worker/sync")).encode("utf-8")
    if method != "POST":
        return 405, json.dumps(error_reply("bad_request", "POST only")).encode("utf-8")
    data = hub.handle_bytes(body)
    return http_status_of(json.loads(data.decode("utf-8"))), data


def wsgi_app(hub: SyncHub) -> Callable[..., Any]:
    def app(environ: Mapping[str, Any], start_response: Callable[..., Any]) -> list[bytes]:
        try:
            size = int(environ.get("CONTENT_LENGTH") or 0)
        except ValueError:
            size = 0
        if size > MAX_SYNC_BYTES + 64 * 1024:
            status, data = 413, json.dumps(error_reply("too_large")).encode("utf-8")
        else:
            body = environ["wsgi.input"].read(size) if size else b""
            status, data = handle_http(hub, str(environ.get("REQUEST_METHOD") or ""), str(environ.get("PATH_INFO") or ""),
                                       body)
        start_response(f"{status} {HTTP_REASONS.get(status, 'Error')}",
                       [("Content-Type", "application/json"), ("Content-Length", str(len(data)))])
        return [data]
    return app


def serve_http(hub: SyncHub, host: str = "127.0.0.1", port: int = 0, *, ready: Callable[[Any], None] | None = None,
               serve: bool = True) -> Any:
    """A `ThreadingHTTPServer` answering `POST /v1/worker/sync`. `ready(server)` is called once it listens (its
    `server_address` has the real port); with `serve=False` the started-but-not-serving server is returned."""
    import http.server  # noqa: PLC0415 - only the resident hub needs the HTTP server modules

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self) -> None:  # noqa: N802 - the http.server hook name
            try:
                size = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                size = 0
            if size > MAX_SYNC_BYTES + 64 * 1024:
                status, data = 413, json.dumps(error_reply("too_large")).encode("utf-8")
                self.close_connection = True
            else:
                status, data = handle_http(hub, "POST", self.path, self.rfile.read(size) if size else b"")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:  # noqa: N802
            status, data = handle_http(hub, "GET", self.path, b"")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, fmt: str, *args: Any) -> None:  # quiet: requests carry nothing worth a log line
            return None

    server = http.server.ThreadingHTTPServer((host, int(port)), Handler)
    server.daemon_threads = True
    if ready is not None:
        ready(server)
    if serve:
        try:
            server.serve_forever()
        finally:
            server.server_close()
    return server


# --- node side --------------------------------------------------------------------------------------------------


class InProcessHubClient:
    """A hub in this process (tests, and a node co-located with its coordinator). `online=False` acts as a
    partition: every call raises `HubUnavailable` before reaching the hub."""

    def __init__(self, hub: SyncHub, *, online: bool = True) -> None:
        self.hub = hub
        self.online = online
        self.calls = 0

    def call(self, request: Mapping[str, Any]) -> dict[str, Any]:
        if not self.online:
            raise HubUnavailable("partitioned (test)")
        self.calls += 1
        return _reply_of(self.hub.handle_bytes(json.dumps(request, ensure_ascii=False)))


class StdioHubClient:
    """`ssh <host> pm.py mailbox-sync --stdio` (or any argv speaking the same lines): one process per request."""

    def __init__(self, argv: Sequence[str], *, timeout_s: float = DEFAULT_TIMEOUT_S, env: Mapping[str, str] | None = None,
                 runner: Callable[..., Any] = subprocess.run) -> None:
        self.argv = [str(a) for a in argv]
        self.timeout_s = float(timeout_s)
        self.env = dict(env) if env is not None else None
        self._run = runner

    def call(self, request: Mapping[str, Any]) -> dict[str, Any]:
        line = json.dumps(request, ensure_ascii=False, separators=(",", ":")) + "\n"
        try:
            res = self._run(self.argv, input=line.encode("utf-8"), capture_output=True, timeout=self.timeout_s,
                            env=self.env)
        except (OSError, subprocess.SubprocessError) as err:
            raise HubUnavailable(f"{self.argv[0]}: {err}") from err
        out = (res.stdout or b"").decode("utf-8", "replace").strip().splitlines()
        if not out:
            tail = (res.stderr or b"").decode("utf-8", "replace").strip()[-300:]
            raise HubUnavailable(f"no reply from {' '.join(self.argv[:2])} (exit {res.returncode}): {tail}")
        return _reply_of(out[-1])


class HttpHubClient:
    """`POST <url>/v1/worker/sync` (`url` is the hub's base URL, or the full endpoint)."""

    def __init__(self, url: str, *, timeout_s: float = DEFAULT_TIMEOUT_S) -> None:
        base = str(url).rstrip("/")
        self.url = base if base.endswith(SYNC_PATHS) else base + SYNC_PATHS[0]
        self.timeout_s = float(timeout_s)

    def call(self, request: Mapping[str, Any]) -> dict[str, Any]:
        return _http_post(self.url, json.dumps(request, ensure_ascii=False).encode("utf-8"), self.timeout_s)


def _http_post(url: str, data: bytes, timeout_s: float) -> dict[str, Any]:
    import urllib.error  # noqa: PLC0415 - only a node talking HTTPS needs the URL modules
    import urllib.request  # noqa: PLC0415

    req = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310 - the configured hub URL
            return _reply_of(resp.read())
    except urllib.error.HTTPError as err:  # a refusal still carries the protocol's JSON error
        try:
            return _reply_of(err.read())
        except HubUnavailable:
            raise HubUnavailable(f"HTTP {err.code} from the hub") from err
    except (urllib.error.URLError, OSError, ValueError) as err:
        raise HubUnavailable(f"{url}: {err}") from err


def client_for(hub: str, *, hub_command: Sequence[str] | None = None, timeout_s: float = DEFAULT_TIMEOUT_S) -> Any:
    """`https://...` / `http://...` -> HTTP; anything else is an SSH host running the stdio command."""
    if hub_command:
        return StdioHubClient(hub_command, timeout_s=timeout_s)
    hub = str(hub or "").strip()
    if hub.startswith(("http://", "https://")):
        return HttpHubClient(hub, timeout_s=timeout_s)
    if not hub:
        raise ValueError("no hub configured")
    return StdioHubClient(ssh_argv(hub), timeout_s=timeout_s)


def ssh_argv(host: str, pm_command: str = "python3 ~/.claude/skills/pm/scripts/pm.py") -> list[str]:
    # `-T`: no terminal; `BatchMode`: never prompt (a node runs unattended). The remote side may pin the command
    # with `command="pm.py mailbox-sync --stdio"` in authorized_keys, so what is asked for here is only a hint.
    return ["ssh", "-T", "-o", "BatchMode=yes", host, f"{pm_command} mailbox-sync --stdio"]
