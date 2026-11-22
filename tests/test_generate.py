from types import SimpleNamespace

import pytest

from sqldash import caps, generate
from sqldash.errors import ServiceError


class FakeClient:
    # Records each messages.create call and returns or raises what it was given.
    def __init__(self, response=None, raises=None):
        self.calls = []
        self._response = response
        self._raises = raises
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kw):
        self.calls.append(kw)
        if self._raises is not None:
            raise self._raises
        return self._response


def block(type_, text=None):
    return SimpleNamespace(type=type_, text=text) if text is not None else SimpleNamespace(type=type_)


def reply_blocks(blocks, stop_reason="end_turn"):
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=blocks,
        usage=SimpleNamespace(input_tokens=11, output_tokens=7),
        model="claude-sonnet-5-5",
    )


def reply(text, stop_reason="end_turn"):
    return reply_blocks([block("text", text)], stop_reason)


def kind_of(fn):
    with pytest.raises(ServiceError) as info:
        fn()
    return info.value


GOOD = '{"sql": "SELECT a\\nFROM t", "note": ""}'


def test_happy_path():
    client = FakeClient(reply(GOOD))
    out = generate.generate("everything in t", "postgres", environ={}, client=client)
    assert out == {"sql": "SELECT a\nFROM t", "note": "", "model": "claude-sonnet-5-5",
                   "input_tokens": 11, "output_tokens": 7}
    kw = client.calls[0]
    assert kw["model"] == "claude-sonnet-5-5"
    assert kw["max_tokens"] == 8000
    assert kw["output_config"] == {"effort": "low", "format": generate.SQL_FORMAT}
    assert generate.SQL_FORMAT["schema"]["required"] == ["sql", "note"]
    assert generate.SQL_FORMAT["schema"]["additionalProperties"] is False
    assert "temperature" not in kw and "thinking" not in kw and "tools" not in kw
    assert kw["system"].startswith("You write PostgreSQL SQL")
    assert "{dialect}" not in kw["system"]
    assert kw["messages"] == [{"role": "user", "content": "Dialect: PostgreSQL\n\neverything in t"}]


def test_model_override():
    client = FakeClient(reply(GOOD))
    generate.generate("x", "mysql", environ={"SQLDASH_SQL_MODEL": "claude-haiku-5-5"}, client=client)
    assert client.calls[0]["model"] == "claude-haiku-5-5"
    assert client.calls[0]["system"].startswith("You write MySQL SQL")


def test_thinking_blocks_are_skipped_and_text_is_trimmed():
    client = FakeClient(reply_blocks([block("thinking"), block("text", '{"sql": "  SELECT 1\\n", "note": " "}')]))
    out = generate.generate("one", "postgres", environ={}, client=client)
    assert (out["sql"], out["note"]) == ("SELECT 1", "")


def test_empty_sql_with_a_note_is_an_answer():
    client = FakeClient(reply('{"sql": "", "note": "Say which table."}'))
    out = generate.generate("the thing", "postgres", environ={}, client=client)
    assert (out["sql"], out["note"]) == ("", "Say which table.")


@pytest.mark.parametrize("text", [
    "not json", '["sql"]', '{"sql": "SELECT 1"}', '{"sql": 1, "note": ""}',
    '{"sql": "SELECT 1", "note": null}', '{"sql": "", "note": ""}', '{"sql": " ", "note": "\\n"}',
])
def test_unusable_replies_are_upstream(text):
    client = FakeClient(reply(text))
    assert kind_of(lambda: generate.generate("x", "postgres", environ={}, client=client)).kind == "upstream"


def test_no_text_block_is_upstream():
    client = FakeClient(reply_blocks([block("thinking")]))
    assert kind_of(lambda: generate.generate("x", "postgres", environ={}, client=client)).kind == "upstream"


def test_empty_and_too_long_never_call_the_model():
    client = FakeClient(reply(GOOD))
    assert kind_of(lambda: generate.generate(" \n", "postgres", environ={}, client=client)).kind == "empty"
    long = "x" * (caps.MAX_SQL_CHARS + 1)
    assert kind_of(lambda: generate.generate(long, "postgres", environ={}, client=client)).kind == "too_long"
    generate.generate("x" * caps.MAX_SQL_CHARS, "postgres", environ={}, client=client)
    assert len(client.calls) == 1


def test_missing_key():
    err = kind_of(lambda: generate.generate("x", "postgres", environ={}))
    assert (err.kind, err.detail) == ("missing_key", "ANTHROPIC_API_KEY")


def test_refusal_and_cut_off():
    for stop, kind in (("refusal", "refusal"), ("max_tokens", "cut_off")):
        client = FakeClient(reply(GOOD, stop_reason=stop))
        assert kind_of(lambda: generate.generate("x", "postgres", environ={}, client=client)).kind == kind


def test_unknown_dialect_raises():
    with pytest.raises(ValueError):
        generate.generate("x", "oracle", environ={}, client=FakeClient(reply(GOOD)))


def test_sdk_errors_map_to_kinds():
    anthropic = pytest.importorskip("anthropic")
    httpx2 = pytest.importorskip("httpx2")
    req = httpx2.Request("POST", "https://x")

    def status(cls, code):
        return cls("secret detail", response=httpx2.Response(code, request=req), body=None)

    cases = [
        (status(anthropic.AuthenticationError, 401), "bad_key"),
        (status(anthropic.RateLimitError, 429), "rate_limit"),
        (anthropic.APITimeoutError(request=req), "timeout"),
        (anthropic.APIConnectionError(request=req), "network"),
        (status(anthropic.InternalServerError, 500), "upstream"),
    ]
    for exc, kind in cases:
        client = FakeClient(raises=exc)
        err = kind_of(lambda: generate.generate("x", "postgres", environ={}, client=client))
        assert err.kind == kind
        assert "secret" not in str(err.detail)
        if kind == "bad_key":
            assert err.detail == "ANTHROPIC_API_KEY"


def test_non_sdk_exception_propagates():
    pytest.importorskip("anthropic")
    client = FakeClient(raises=RuntimeError("boom"))
    with pytest.raises(RuntimeError):
        generate.generate("x", "postgres", environ={}, client=client)


def test_line_endings_become_newlines():
    client = FakeClient(reply('{"sql": "SELECT a\\r\\nFROM t\\rWHERE b", "note": ""}'))
    out = generate.generate("x", "postgres", environ={}, client=client)
    assert out["sql"] == "SELECT a\nFROM t\nWHERE b"
