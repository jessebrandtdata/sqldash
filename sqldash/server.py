"""A stdlib HTTP server: a small JSON API plus the built page in dist/."""
import ipaddress
import json
import os
import sys
import traceback
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import unquote, urlsplit

from . import caps, checker, envfile, errors, generate, judge, names, summary, theme

MAX_BODY = 1_048_576
DRAIN_LIMIT = 8 * 1024 * 1024
CHUNK = 65536
LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost"})
WILDCARD = frozenset({"0.0.0.0", "::"})

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".txt": "text/plain; charset=utf-8",
    ".woff2": "font/woff2",
}

# (method, path) -> name of the handler method
ROUTES = {
    ("GET", "/api/caps"): "_route_caps",
    ("POST", "/api/check"): "_route_check",
    ("POST", "/api/summary"): "_route_summary",
    ("POST", "/api/judge"): "_route_judge",
    ("POST", "/api/sql"): "_route_sql",
    ("POST", "/api/names"): "_route_names",
    ("GET", "/theme.css"): "_route_theme",
}

# the string fields each POST route requires, in call order
FIELDS = {
    "/api/check": ("sql", "dialect"),
    "/api/summary": ("sql", "dialect"),
    "/api/judge": ("sql", "english", "dialect"),
    "/api/sql": ("english", "dialect"),
    "/api/names": ("sql", "dialect"),
}


@dataclass
class Services:
    """The functions the routes call; defaults are the real ones on os.environ."""

    check: Callable = checker.check
    summarize: Callable = field(default=lambda sql, dialect: summary.summarize(sql, dialect, environ=os.environ))
    judge: Callable = field(
        default=lambda sql, english, dialect: judge.judge(sql, english, dialect, environ=os.environ)
    )
    generate: Callable = field(default=lambda english, dialect: generate.generate(english, dialect, environ=os.environ))
    names: Callable = names.read_names
    capabilities: Callable = field(default=lambda: caps.capabilities(os.environ))


class _Handler(BaseHTTPRequestHandler):
    dist: Path
    services: Services
    bound_host: str = "127.0.0.1"
    allowed_hosts: frozenset = frozenset()
    protocol_version = "HTTP/1.1"
    server_version = "sqldash"
    # a stalled client is dropped after this many seconds
    timeout = 30

    # ---- output helpers ----
    def _send(self, status, body: bytes, ctype, extra=None, close=False):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        if close:
            self.send_header("Connection", "close")
            self.close_connection = True
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status, payload, close=False):
        body = json.dumps(payload).encode()
        self._send(status, body, "application/json; charset=utf-8", close=close)

    def _fail(self, kind, detail="", close=False):
        self._json(
            errors.STATUS[kind],
            {"error": {"kind": kind, "message": errors.sentence(kind, var=detail)}},
            close=close,
        )

    # ---- logging ----
    def log_request(self, code="-", size="-"):
        path = urlsplit(self.path).path
        print(f"{self.command} {path} {code}", file=sys.stderr, flush=True)

    def log_error(self, *args):
        pass

    def send_error(self, code, message=None, explain=None):
        # replace the default HTML error page with the JSON shape
        kind = {404: "not_found", 413: "too_big"}.get(code, "bad_request" if code < 500 else "internal")
        self.command = self.command or "-"
        self._fail(kind, close=True)

    # ---- dispatch ----
    def _path(self):
        return unquote(urlsplit(self.path).path)

    # ---- request checks ----
    @staticmethod
    def _hostname(value):
        # The host part of a Host header value: port dropped, IPv6 brackets stripped, lower case.
        value = value.strip().lower()
        if value.startswith("["):
            end = value.find("]")
            return value[1:end] if end > 0 else ""
        return value.partition(":")[0]

    def _host_allowed(self, name):
        if name in self.allowed_hosts:
            return True
        bound = self.bound_host.strip("[]").lower()
        if bound in LOOPBACK:
            return name in LOOPBACK
        if bound in WILDCARD:
            if name == "localhost":
                return True
            try:
                ipaddress.ip_address(name)
            except ValueError:
                return False
            return True
        return name == bound

    def _forbidden(self):
        # The Host or Origin header is not one this server answers to.
        host = self.headers.get("Host")
        if host is None or not self._host_allowed(self._hostname(host)):
            return True
        origin = self.headers.get("Origin")
        return origin is not None and urlsplit(origin).netloc.lower() != host.strip().lower()

    def _drain_body(self):
        # Read and discard a declared body so the client can finish sending before the answer.
        raw = self.headers.get("Content-Length", "")
        if raw.strip().isdigit() and int(raw) <= DRAIN_LIMIT:
            left = int(raw)
            while left > 0:
                chunk = self.rfile.read(min(CHUNK, left))
                if not chunk:
                    break
                left -= len(chunk)

    def _refuse(self, kind):
        # Answer a failed request check after draining the body, then close.
        try:
            self._drain_body()
        except OSError:
            pass
        self._fail(kind, close=True)

    def do_GET(self):
        if self._forbidden():
            self._refuse("forbidden")
            return
        path = self._path()
        name = ROUTES.get(("GET", path))
        if name:
            self._guarded(getattr(self, name))
        elif path.startswith("/api/"):
            self._fail("not_found")
        else:
            self._file(path)

    do_HEAD = do_GET

    def do_POST(self):
        if self._forbidden():
            self._refuse("forbidden")
            return
        name = ROUTES.get(("POST", self._path()))
        if not name:
            # the body is left unread, so the connection cannot be reused
            self._fail("not_found", close=True)
            return
        media = self.headers.get("Content-Type", "").partition(";")[0].strip().lower()
        if media != "application/json":
            self._refuse("bad_request")
            return
        self._guarded(getattr(self, name))

    def _other(self):
        self._fail("not_found", close=True)

    do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _other

    def _guarded(self, fn):
        try:
            fn()
        except errors.ServiceError as e:
            self._fail(e.kind, e.detail)
        except TimeoutError:
            # a stalled client: drop the connection without an answer
            self.close_connection = True
        except ValueError:
            self._fail("bad_request")
        except Exception as e:
            # log the class and frames only: the message may quote a key
            frames = " ".join(
                f"{os.path.basename(f.filename)}:{f.lineno}" for f in traceback.extract_tb(e.__traceback__)
            )
            print(f"internal {type(e).__name__} {frames}", file=sys.stderr, flush=True)
            self._fail("internal")

    # ---- request body ----
    def _read_body(self) -> dict:
        """Return the JSON object body; raise ServiceError for any bad body."""
        if "chunked" in self.headers.get("Transfer-Encoding", "").lower():
            raise errors.ServiceError("bad_request")
        raw = self.headers.get("Content-Length")
        if raw is None or not raw.strip().isdigit():
            raise errors.ServiceError("bad_request")
        length = int(raw)
        if length > MAX_BODY:
            if length <= DRAIN_LIMIT:
                # read and discard the declared body so the client can finish sending
                left = length
                while left > 0:
                    chunk = self.rfile.read(min(CHUNK, left))
                    if not chunk:
                        break
                    left -= len(chunk)
            self.close_connection = True
            raise _TooBig()
        data = self.rfile.read(length)
        try:
            body = json.loads(data)
        except ValueError:
            raise errors.ServiceError("bad_request")
        if not isinstance(body, dict):
            raise errors.ServiceError("bad_request")
        return body

    def _fields(self):
        names = FIELDS[self._path()]
        body = self._read_body()
        if not all(isinstance(body.get(n), str) for n in names):
            raise errors.ServiceError("bad_request")
        return [body[n] for n in names]

    # ---- routes ----
    def _route_caps(self):
        self._json(200, self.services.capabilities())

    def _route_check(self):
        self._json(200, self.services.check(*self._fields()))

    def _route_summary(self):
        self._json(200, self.services.summarize(*self._fields()))

    def _route_judge(self):
        self._json(200, self.services.judge(*self._fields()))

    def _route_sql(self):
        self._json(200, self.services.generate(*self._fields()))

    def _route_names(self):
        self._json(200, self.services.names(*self._fields()))

    def _route_theme(self):
        self._send(200, theme.theme_css().encode(), "text/css; charset=utf-8", {"Cache-Control": "no-store"})

    # ---- files ----
    def _file(self, path):
        rel = "index.html" if path == "/" else path.lstrip("/")
        try:
            root = self.dist.resolve()
            target = (root / rel).resolve()
            ok = "\0" not in rel and target.is_relative_to(root) and target.is_file()
            data = target.read_bytes() if ok else b""
        except (OSError, ValueError):
            ok = False
        if not ok:
            self._fail("not_found")
            return
        ctype = CONTENT_TYPES.get(target.suffix.lower(), "application/octet-stream")
        self._send(200, data, ctype, {"Cache-Control": "no-cache"})


class _TooBig(errors.ServiceError):
    def __init__(self):
        super().__init__("too_big")


def make_server(
    host: str, port: int, dist: Path, services: Services, *, allowed_hosts: frozenset[str] = frozenset()
) -> ThreadingHTTPServer:
    """Build a server whose handler is bound to this dist, these services and these Host names."""
    handler = type(
        "Handler",
        (_Handler,),
        {
            "dist": Path(dist),
            "services": services,
            "bound_host": host,
            "allowed_hosts": frozenset(n.lower() for n in allowed_hosts),
        },
    )
    srv = ThreadingHTTPServer((host, port), handler)
    srv.daemon_threads = True
    return srv


def main(argv):
    host = argv[0] if len(argv) > 0 else "127.0.0.1"
    port = int(argv[1]) if len(argv) > 1 else 8096
    envfile.load_env_file(envfile.default_path(os.environ), os.environ)
    dist = Path(__file__).resolve().parent.parent / "dist"
    names = os.environ.get("SQLDASH_ALLOWED_HOSTS", "")
    allowed = frozenset(n.strip().lower() for n in names.split(",") if n.strip())
    srv = make_server(host, port, dist, Services(), allowed_hosts=allowed)
    print(f"sqldash on http://{host}:{srv.server_address[1]}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


if __name__ == "__main__":
    main(sys.argv[1:])
