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
        self.check_fn = lambda sql, dialect: {"ok": True, "sql": sql, "dialect": dialect}
        self.summarize_fn = lambda sql, dialect: {"summary": "s"}
        self.judge_fn = lambda sql, english, dialect: {"verdict": "v"}

    def services(self):
        def check(sql, dialect):
            self.calls.append(("check", sql, dialect))
            return self.check_fn(sql, dialect)

        return server.Services(
            check=check,
            summarize=lambda sql, dialect: self.summarize_fn(sql, dialect),
            judge=lambda sql, english, dialect: self.judge_fn(sql, english, dialect),
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
    for method in ("PUT", "DELETE", "HEAD"):
        conn = http.client.HTTPConnection(host, int(port), timeout=3)
        conn.request(method, "/api/caps")
        resp = conn.getresponse()
        body = resp.read()
        assert resp.status == 404
        if method != "HEAD":
            assert json.loads(body)["error"]["kind"] == "not_found"
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
