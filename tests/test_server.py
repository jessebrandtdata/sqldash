import http.client
import json
import threading
import time
import urllib.error
import urllib.request

import pytest

from sqldash import server
from sqldash.errors import ServiceError


class Fakes:
    def __init__(self):
        self.calls = []
        self.service_calls = 0
        self.check_fn = lambda sql, dialect: {"ok": True, "sql": sql, "dialect": dialect}
        self.summarize_fn = lambda sql, dialect: {"summary": "s"}
        self.judge_fn = lambda sql, english, dialect: {"verdict": "v"}

    def services(self):
        def check(sql, dialect):
            self.service_calls += 1
            self.calls.append(("check", sql, dialect))
            return self.check_fn(sql, dialect)

        def summarize(sql, dialect):
            self.service_calls += 1
            return self.summarize_fn(sql, dialect)

        def judge(sql, english, dialect):
            self.service_calls += 1
            return self.judge_fn(sql, english, dialect)

        return server.Services(
            check=check,
            summarize=summarize,
            judge=judge,
            capabilities=lambda: {"caps": True},
        )


@pytest.fixture
def dist(tmp_path):
    d = tmp_path / "dist"
    (d / "docs").mkdir(parents=True)
    (d / "index.html").write_text("<h1>hi</h1>")
    (d / "docs" / "x.json").write_text('{"a": 1}')
    (tmp_path / "secret.txt").write_text("nope")
    return d


@pytest.fixture
def fakes():
    return Fakes()


@pytest.fixture
def base(dist, fakes):
    srv = server.make_server("127.0.0.1", 0, dist, fakes.services())
    t = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def get(url):
    try:
        with urllib.request.urlopen(url) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


def post(url, body, raw=False):
    data = body if raw else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.headers, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, e.headers, json.loads(e.read())


def test_index_and_static(base):
    status, headers, body = get(base + "/")
    assert status == 200 and body == b"<h1>hi</h1>"
    assert headers["Content-Type"].startswith("text/html")
    assert headers["Cache-Control"] == "no-cache"
    status, headers, body = get(base + "/docs/x.json")
    assert status == 200 and headers["Content-Type"] == "application/json"
    assert json.loads(body) == {"a": 1}


def test_path_traversal(base):
    for path in ("/../sqldash/words.py", "/%2e%2e/serve", "/%2e%2e/secret.txt", "/docs", "/missing.js"):
        status, _, body = get(base + path)
        assert status == 404, path
        assert json.loads(body)["error"]["kind"] == "not_found"


def test_check_route(base, fakes):
    status, headers, body = post(base + "/api/check", {"sql": "select 1", "dialect": "postgres"})
    assert status == 200
    assert headers["Content-Type"] == "application/json; charset=utf-8"
    assert body == {"ok": True, "sql": "select 1", "dialect": "postgres"}
    assert fakes.calls == [("check", "select 1", "postgres")]


def test_unknown_dialect(base, fakes):
    def boom(sql, dialect):
        raise ValueError("unknown dialect")

    fakes.check_fn = boom
    status, _, body = post(base + "/api/check", {"sql": "x", "dialect": "nope"})
    assert status == 400 and body["error"]["kind"] == "bad_request"


def test_bad_json_and_missing_fields(base):
    for raw in (b"not json", b"[]", b'{"sql": 1, "dialect": "postgres"}', b'{"sql": "x"}'):
        status, _, body = post(base + "/api/check", raw, raw=True)
        assert status == 400 and body["error"]["kind"] == "bad_request", raw


def test_service_error_shape(base, fakes):
    from sqldash import errors

    def boom(sql, english, dialect):
        raise ServiceError("rate_limit")

    fakes.judge_fn = boom
    status, _, body = post(base + "/api/judge", {"sql": "x", "english": "y", "dialect": "postgres"})
    assert status == 429
    assert body == {"error": {"kind": "rate_limit", "message": errors.sentence("rate_limit")}}


def test_missing_key_names_variable(base, fakes):
    def boom(sql, dialect):
        raise ServiceError("missing_key", "TYPESAFE_API_KEY")

    fakes.summarize_fn = boom
    status, _, body = post(base + "/api/summary", {"sql": "x", "dialect": "postgres"})
    assert status == 503
    assert body["error"]["message"].startswith("TYPESAFE_API_KEY is not set")


def test_unexpected_exception(base, fakes, capsys):
    def boom(sql, dialect):
        raise RuntimeError("sk-secret boom")

    fakes.check_fn = boom
    status, _, body = post(base + "/api/check", {"sql": "x", "dialect": "postgres"})
    assert status == 500 and body["error"]["kind"] == "internal"
    text = json.dumps(body)
    assert "secret" not in text and "Traceback" not in text
    time.sleep(0.1)
    captured = capsys.readouterr()
    assert "RuntimeError" in captured.err
    assert "secret" not in captured.err and "secret" not in captured.out


def test_body_over_1mb(base):
    start = time.time()
    status, _, body = post(base + "/api/check", b"x" * 1_048_577, raw=True)
    assert status == 413 and body["error"]["kind"] == "too_big"
    assert time.time() - start < 2


def test_body_declared_over_8mb(base):
    host, port = base[len("http://"):].split(":")
    conn = http.client.HTTPConnection(host, int(port), timeout=3)
    conn.putrequest("POST", "/api/check")
    conn.putheader("Content-Type", "application/json")
    conn.putheader("Content-Length", str(50_000_000))
    conn.endheaders()
    resp = conn.getresponse()
    assert resp.status == 413
    assert json.loads(resp.read())["error"]["kind"] == "too_big"
    conn.close()


def test_missing_and_bad_content_length(base):
    host, port = base[len("http://"):].split(":")
    for headers in ({}, {"Content-Length": "abc"}, {"Transfer-Encoding": "chunked"}):
        conn = http.client.HTTPConnection(host, int(port), timeout=3)
        conn.putrequest("POST", "/api/check", skip_accept_encoding=True)
        for k, v in headers.items():
            conn.putheader(k, v)
        conn.endheaders()
        resp = conn.getresponse()
        assert resp.status == 400, headers
        assert json.loads(resp.read())["error"]["kind"] == "bad_request"
        conn.close()


def test_check_accepts_large_sql(base, fakes):
    sql = "x" * 900_000
    status, _, body = post(base + "/api/check", {"sql": sql, "dialect": "postgres"})
    assert status == 200
    assert fakes.calls[0][1] == sql


def test_theme_css(base):
    status, headers, _ = get(base + "/theme.css")
    assert status == 200
    assert headers["Content-Type"].startswith("text/css")
    assert headers["Cache-Control"] == "no-store"


def test_caps_route(base):
    status, _, body = get(base + "/api/caps")
    assert status == 200 and json.loads(body) == {"caps": True}


def test_unknown_api_route(base):
    for path in ("/api/nope", "/api/check"):
        status, _, body = get(base + path)
        assert status == 404 and json.loads(body)["error"]["kind"] == "not_found"


def test_other_methods_are_404_json(base):
    host, port = base[len("http://"):].split(":")
    for method in ("PUT", "DELETE", "PATCH", "OPTIONS"):
        conn = http.client.HTTPConnection(host, int(port), timeout=3)
        conn.request(method, "/api/caps")
        resp = conn.getresponse()
        body = resp.read()
        assert resp.status == 404
        assert json.loads(body)["error"]["kind"] == "not_found"
        assert not [h for h, _ in resp.getheaders() if h.lower().startswith("access-control")]
        conn.close()


def test_head_answers_like_get_without_a_body(base):
    host, port = base[len("http://"):].split(":")
    for path in ("/", "/docs/x.json", "/api/caps", "/theme.css"):
        conn = http.client.HTTPConnection(host, int(port), timeout=3)
        conn.request("GET", path)
        got = conn.getresponse()
        got_body = got.read()
        conn.request("HEAD", path)
        head = conn.getresponse()
        assert head.read() == b"", path
        assert head.status == got.status == 200, path
        assert head.getheader("Content-Type") == got.getheader("Content-Type")
        assert head.getheader("Content-Length") == str(len(got_body))
        conn.close()


def test_head_on_a_post_route_or_missing_file_is_404(base):
    host, port = base[len("http://"):].split(":")
    for path in ("/api/check", "/missing.js"):
        conn = http.client.HTTPConnection(host, int(port), timeout=3)
        conn.request("HEAD", path)
        resp = conn.getresponse()
        assert resp.status == 404 and resp.read() == b""
        conn.close()


def test_servers_do_not_share_state(tmp_path, fakes):
    a, b = tmp_path / "a", tmp_path / "b"
    for d, text in ((a, "A"), (b, "B")):
        d.mkdir()
        (d / "index.html").write_text(text)
    s1 = server.make_server("127.0.0.1", 0, a, fakes.services())
    s2 = server.make_server("127.0.0.1", 0, b, fakes.services())
    for s in (s1, s2):
        threading.Thread(target=s.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()
    try:
        assert get(f"http://127.0.0.1:{s1.server_address[1]}/")[2] == b"A"
        assert get(f"http://127.0.0.1:{s2.server_address[1]}/")[2] == b"B"
    finally:
        for s in (s1, s2):
            s.shutdown()
            s.server_close()


def test_no_blocked_route_names():
    blocked = ("stat", "track", "collect", "pixel", "beacon", "analytics", "pageview", "ads")
    for _method, path in server.ROUTES:
        assert not any(f in path for f in blocked), path


# ---- request checks: Host, Content-Type, Origin ----


def raw(base, method, path, headers=None, body=b"", host="default"):
    # Sends one request with exactly the headers given; host="default" sends the real Host.
    h, port = base[len("http://"):].split(":")
    conn = http.client.HTTPConnection(h, int(port), timeout=3)
    conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
    if host == "default":
        conn.putheader("Host", f"{h}:{port}")
    elif host is not None:
        conn.putheader("Host", host)
    for k, v in (headers or {}).items():
        conn.putheader(k, v)
    if method == "POST":
        conn.putheader("Content-Length", str(len(body)))
    conn.endheaders(body)
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    return resp.status, resp, json.loads(data) if data else None


GOOD = json.dumps({"sql": "select 1", "dialect": "postgres"}).encode()
JSON = {"Content-Type": "application/json"}
FORBIDDEN_TEXT = "sqldash does not answer to this address. Add its name to SQLDASH_ALLOWED_HOSTS."


def test_foreign_host_is_forbidden_on_get_and_post(base, fakes):
    status, _, body = raw(base, "GET", "/", host="evil.example")
    assert status == 403
    assert body == {"error": {"kind": "forbidden", "message": FORBIDDEN_TEXT}}
    status, _, body = raw(base, "POST", "/api/check", JSON, GOOD, host="evil.example")
    assert status == 403 and body["error"]["kind"] == "forbidden"
    assert fakes.service_calls == 0


def test_missing_host_is_forbidden(base, fakes):
    status, _, body = raw(base, "POST", "/api/check", JSON, GOOD, host=None)
    assert status == 403 and body["error"]["kind"] == "forbidden"
    assert fakes.service_calls == 0


def test_loopback_bound_server_accepts_loopback_names(base):
    port = base.rsplit(":", 1)[1]
    for host in (f"localhost:{port}", f"LOCALHOST:{port}", f"[::1]:{port}", "127.0.0.1"):
        status, _, _ = raw(base, "GET", "/api/caps", host=host)
        assert status == 200, host


def serve_on(dist, fakes, bound, **kw):
    srv = server.make_server(bound, 0, dist, fakes.services(), **kw)
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()
    return srv


def test_allowed_hosts_keyword_adds_names(dist, fakes):
    srv = serve_on(dist, fakes, "127.0.0.1", allowed_hosts=frozenset({"box.example"}))
    try:
        url = f"http://127.0.0.1:{srv.server_address[1]}"
        assert raw(url, "GET", "/api/caps", host="box.example:8096")[0] == 200
        assert raw(url, "GET", "/api/caps", host="BOX.example")[0] == 200
        assert raw(url, "GET", "/api/caps", host="other.example")[0] == 403
    finally:
        srv.shutdown()
        srv.server_close()


def test_other_bound_host_is_not_given_localhost(dist, fakes):
    # a server bound to a non-loopback name accepts that name only; 127.0.0.2 stands in for it
    srv = serve_on(dist, fakes, "127.0.0.2")
    try:
        url = f"http://127.0.0.2:{srv.server_address[1]}"
        assert raw(url, "GET", "/api/caps", host="127.0.0.2")[0] == 200
        assert raw(url, "GET", "/api/caps", host="localhost")[0] == 403
        assert raw(url, "GET", "/api/caps", host="127.0.0.1")[0] == 403
    finally:
        srv.shutdown()
        srv.server_close()


def test_wildcard_bound_server_accepts_ip_literals_and_localhost(dist, fakes):
    srv = serve_on(dist, fakes, "0.0.0.0")
    try:
        url = f"http://127.0.0.1:{srv.server_address[1]}"
        for host in ("192.168.1.5:8096", "10.0.0.1", "[fe80::1]:80", "localhost"):
            assert raw(url, "GET", "/api/caps", host=host)[0] == 200, host
        assert raw(url, "GET", "/api/caps", host="evil.example")[0] == 403
    finally:
        srv.shutdown()
        srv.server_close()


def test_non_json_content_type_is_refused_before_the_service(base, fakes):
    for ctype in ("text/plain", "application/x-www-form-urlencoded", "text/plain;application/json"):
        status, _, body = raw(base, "POST", "/api/check", {"Content-Type": ctype}, GOOD)
        assert status == 400 and body["error"]["kind"] == "bad_request", ctype
    status, _, body = raw(base, "POST", "/api/check", {}, GOOD)
    assert status == 400
    assert fakes.service_calls == 0


def test_json_content_type_with_parameters_is_accepted(base, fakes):
    status, _, _ = raw(base, "POST", "/api/check", {"Content-Type": "application/json; charset=utf-8"}, GOOD)
    assert status == 200
    status, _, _ = raw(base, "POST", "/api/check", {"Content-Type": "Application/JSON"}, GOOD)
    assert status == 200
    assert fakes.service_calls == 2


def test_foreign_origin_is_forbidden_before_the_service(base, fakes):
    for origin in ("http://evil.example", "null"):
        headers = dict(JSON, Origin=origin)
        status, resp, body = raw(base, "POST", "/api/check", headers, GOOD)
        assert status == 403 and body["error"]["kind"] == "forbidden", origin
    status, _, _ = raw(base, "GET", "/api/caps", {"Origin": "http://evil.example"})
    assert status == 403
    assert fakes.service_calls == 0


def test_matching_origin_is_accepted(base, fakes):
    h, port = base[len("http://"):].split(":")
    status, resp, _ = raw(base, "POST", "/api/check", dict(JSON, Origin=base), GOOD)
    assert status == 200
    status, _, _ = raw(base, "POST", "/api/check", dict(JSON, Origin=base.upper().replace("HTTP", "http")), GOOD)
    assert status == 200
    assert not [k for k, _ in resp.getheaders() if k.lower().startswith("access-control")]
    assert fakes.service_calls == 2


def test_forbidden_kind_is_403():
    from sqldash import errors

    assert errors.STATUS["forbidden"] == 403
    assert errors.sentence("forbidden") == FORBIDDEN_TEXT


# ---- socket timeout ----


def test_handler_has_a_30_second_socket_timeout(base, fakes, dist):
    srv = server.make_server("127.0.0.1", 0, dist, fakes.services())
    try:
        assert srv.RequestHandlerClass.timeout == 30
    finally:
        srv.server_close()


def test_stalled_client_is_dropped_without_a_traceback(dist, fakes, capsys):
    import socket

    srv = server.make_server("127.0.0.1", 0, dist, fakes.services())
    srv.RequestHandlerClass.timeout = 0.3
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()
    port = srv.server_address[1]
    try:
        # stalls in the headers
        a = socket.create_connection(("127.0.0.1", port), timeout=3)
        a.sendall(b"GET / HTTP/1.1\r\nHost: 127.0.0.1")
        # stalls in the body
        b = socket.create_connection(("127.0.0.1", port), timeout=3)
        b.sendall(f"POST /api/check HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nContent-Type: application/json\r\nContent-Length: 50\r\n\r\n{{".encode())
        for sock in (a, b):
            sock.settimeout(3)
            while sock.recv(4096):
                pass
            sock.close()
        time.sleep(0.1)
    finally:
        srv.shutdown()
        srv.server_close()
    assert "Traceback" not in capsys.readouterr().err
