from types import SimpleNamespace

import pytest

from sqldash import summary
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


def reply(content=None, stop_reason="end_turn"):
    if content is None:
        content = [block("text", "Ok.")]
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=content,
        usage=SimpleNamespace(input_tokens=11, output_tokens=7),
        model="claude-haiku-5-5",
    )


def kind_of(fn):
    with pytest.raises(ServiceError) as info:
        fn()
    return info.value


def test_happy_path():
    client = FakeClient(reply([block("thinking"), block("text", "A."), block("text", "B.")]))
    out = summary.summarize("select 1", "postgres", environ={}, client=client)
    assert out == {"text": "A.\nB.", "model": "claude-haiku-5-5", "input_tokens": 11, "output_tokens": 7}
    kw = client.calls[0]
    assert kw["model"] == "claude-haiku-5-5"
    assert kw["max_tokens"] == 4000
    assert kw["output_config"] == {"effort": "low"}
    assert "temperature" not in kw
    assert "thinking" not in kw
    assert "PostgreSQL" in kw["system"]
    assert kw["messages"][0]["role"] == "user"
    assert kw["messages"][0]["content"].startswith("Dialect: PostgreSQL\n\n")


def test_model_override():
    client = FakeClient(reply())
    summary.summarize("select 1", "postgres", environ={"SQLDASH_SUMMARY_MODEL": "claude-sonnet-5-5"}, client=client)
    assert client.calls[0]["model"] == "claude-sonnet-5-5"


def test_empty_sql():
    client = FakeClient(reply())
    assert kind_of(lambda: summary.summarize("  \n", "postgres", environ={}, client=client)).kind == "empty"
    assert client.calls == []


def test_too_long():
    client = FakeClient(reply())
    assert kind_of(lambda: summary.summarize("x" * 50_001, "postgres", environ={}, client=client)).kind == "too_long"
    assert client.calls == []


def test_exactly_at_cap():
    client = FakeClient(reply())
    summary.summarize("x" * 50_000, "postgres", environ={}, client=client)
    assert len(client.calls) == 1


def test_missing_key():
    err = kind_of(lambda: summary.summarize("select 1", "postgres", environ={}, client=None))
    assert (err.kind, err.detail) == ("missing_key", "ANTHROPIC_API_KEY")


def test_refusal():
    client = FakeClient(reply(stop_reason="refusal"))
    assert kind_of(lambda: summary.summarize("select 1", "postgres", environ={}, client=client)).kind == "refusal"


def test_cut_off():
    client = FakeClient(reply(stop_reason="max_tokens"))
    assert kind_of(lambda: summary.summarize("select 1", "postgres", environ={}, client=client)).kind == "cut_off"


def test_no_text_block():
    client = FakeClient(reply([block("thinking")]))
    assert kind_of(lambda: summary.summarize("select 1", "postgres", environ={}, client=client)).kind == "upstream"


def test_sdk_errors_map():
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
        err = kind_of(lambda: summary.summarize("select 1", "postgres", environ={}, client=client))
        assert err.kind == kind
        assert "secret" not in str(err.detail)
        if kind == "bad_key":
            assert err.detail == "ANTHROPIC_API_KEY"


def test_none_token_counts_become_zero():
    r = reply()
    r.usage = SimpleNamespace(input_tokens=None, output_tokens=None)
    out = summary.summarize("select 1", "postgres", environ={}, client=FakeClient(r))
    assert (out["input_tokens"], out["output_tokens"]) == (0, 0)
