"""Browser dashboard (`pm.py dash`): serves `assets/dash.html` and `/api/state`. Layer 4.

The HTTP server and browser modules are imported lazily inside `cmd_dash` so ordinary CLI invocations do not pay for
them; they are whitelisted in `tests/test_layers.py` (`LATE_IMPORTS`)."""
import json

from ..procs import launcher
from .state import dash_state

DASH_HTML = launcher().parent.parent / "assets" / "dash.html"


def cmd_dash(a, ctx=None):
    import http.server
    import threading
    import time
    import webbrowser
    lock, cache = threading.Lock(), {"at": 0.0, "body": b""}

    class Handler(http.server.BaseHTTPRequestHandler):
        # The stdlib default (HTTP/0.9) answers an unparsable request, such as a browser trying
        # https first, with a bare body and no headers, which some browsers save as a file.
        default_request_version = "HTTP/1.0"

        def do_HEAD(self):
            self.do_GET(head=True)

        def do_GET(self, head=False):
            if self.path.split("?")[0] == "/api/state":
                with lock:  # one herdr call per second however many tabs are open
                    if time.time() - cache["at"] > 1:
                        cache["body"] = json.dumps(dash_state(ctx=ctx), ensure_ascii=False).encode()
                        cache["at"] = time.time()
                    body, kind = cache["body"], "application/json; charset=utf-8"
            elif self.path.split("?")[0] in ("/", "/index.html"):
                body, kind = DASH_HTML.read_bytes(), "text/html; charset=utf-8"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if not head:
                self.wfile.write(body)

        def log_message(self, fmt, *args):
            line = fmt % args
            if '"GET /api/state' in line and '" 200 ' in line:
                return  # the page polls every 3 s; log only page loads and errors
            ua = self.headers.get("User-Agent", "-") if getattr(self, "headers", None) else "-"
            print(f"{self.log_date_time_string()} {self.client_address[0]} {line} [{ua}]", flush=True)

    server = http.server.ThreadingHTTPServer((a.host, a.port), Handler)
    url = f"http://{'127.0.0.1' if a.host in ('0.0.0.0', '') else a.host}:{a.port}/"
    print(f"PM dashboard on {url}  (ctrl+c to stop)", flush=True)
    if a.host in ("0.0.0.0", ""):
        import socket
        try:  # the address other devices on the LAN reach this machine at (no packet is sent)
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("10.255.255.255", 1))
                print(f"on the LAN: http://{s.getsockname()[0]}:{a.port}/", flush=True)
        except OSError:
            pass
    if a.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


def register_dash_view(sub):
    ds = sub.add_parser("dash", help="serve the live dashboard (routing view of PMs, tasks and agents)")
    ds.add_argument("--port", type=int, default=7317)
    ds.add_argument("--host", default="127.0.0.1")
    ds.add_argument("--open", action="store_true", help="open it in the browser")
