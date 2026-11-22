from types import SimpleNamespace

import pytest

typesafe_sdk = pytest.importorskip("typesafe_sdk")
httpx2 = pytest.importorskip("httpx2")

from sqldash import judge
from sqldash.errors import ServiceError


class FakeClient:
    # Records each system_one call and returns or raises what it was given.
    def __init__(self, response=None, raises=None):
        self.calls = []
        self._response = response
        self._raises = raises

    def system_one(self, state, questions):
        self.calls.append((state, questions))
        if self._raises is not None:
            raise self._raises
        return self._response


def reply(choice="agrees", confidence=0.8, answers=None):
    if answers is None:
        probs = {"agrees": 0.8, "differs": 0.15, "cannot_tell": 0.05}
        answers = {"agreement": SimpleNamespace(choice=choice, confidence=confidence, probabilities=probs)}
    return SimpleNamespace(answers=answers, model="jev-1")


def kind_of(fn):
    with pytest.raises(ServiceError) as info:
        fn()
    return info.value


def test_happy_path():
    client = FakeClient(reply("differs", 0.91))
    out = judge.judge("select 1", "one", "mysql", environ={}, client=client)
    assert out == {
        "choice": "differs",
        "confidence": 0.91,
        "probabilities": {"agrees": 0.8, "differs": 0.15, "cannot_tell": 0.05},
        "model": "jev-1",
    }
    state, questions = client.calls[0]
    assert state == {"dialect": "MySQL", "sql": "select 1", "english": "one"}
    assert list(questions) == ["agreement"]
    assert list(questions["agreement"].criteria) == ["agrees", "differs", "cannot_tell"]


def test_empty_either_side():
    client = FakeClient(reply())
    assert kind_of(lambda: judge.judge(" ", "one", "postgres", environ={}, client=client)).kind == "empty"
    assert kind_of(lambda: judge.judge("select 1", "\n", "postgres", environ={}, client=client)).kind == "empty"
    assert client.calls == []


def test_too_long():
    client = FakeClient(reply())
    assert kind_of(lambda: judge.judge("x" * 50_001, "one", "postgres", environ={}, client=client)).kind == "too_long"
    assert client.calls == []


def test_missing_key():
    err = kind_of(lambda: judge.judge("select 1", "one", "postgres", environ={}, client=None))
    assert (err.kind, err.detail) == ("missing_key", "TYPESAFE_API_KEY")


def test_answer_missing():
    client = FakeClient(reply(answers={}))
    assert kind_of(lambda: judge.judge("select 1", "one", "postgres", environ={}, client=client)).kind == "upstream"


def test_choice_outside_criteria():
    client = FakeClient(reply("maybe"))
    assert kind_of(lambda: judge.judge("select 1", "one", "postgres", environ={}, client=client)).kind == "upstream"


def test_sdk_errors_map():
    t = typesafe_sdk
    h = httpx2.Headers()
    cases = [
        (t.TypeSafeAuthenticationError(401, {}, h, "secret detail"), "bad_key"),
        (t.TypeSafeRateLimitError(429, {}, h, "secret detail"), "rate_limit"),
        (t.TypeSafeAPITimeoutError(20.0), "timeout"),
        (t.TypeSafeAPIConnectionError("secret detail"), "network"),
        (t.TypeSafeInternalServerError(500, {}, h, "secret detail"), "upstream"),
    ]
    for exc, kind in cases:
        client = FakeClient(raises=exc)
        err = kind_of(lambda: judge.judge("select 1", "one", "postgres", environ={}, client=client))
        assert err.kind == kind
        assert "secret" not in str(err.detail)
        if kind == "bad_key":
            assert err.detail == "TYPESAFE_API_KEY"


def test_confidence_missing_none_or_not_a_number():
    for bad in (None, "high", object()):
        client = FakeClient(reply("agrees", bad))
        assert kind_of(lambda: judge.judge("select 1", "one", "postgres", environ={}, client=client)).kind == "upstream"
    answer = SimpleNamespace(choice="agrees", probabilities={})
    client = FakeClient(reply(answers={"agreement": answer}))
    assert kind_of(lambda: judge.judge("select 1", "one", "postgres", environ={}, client=client)).kind == "upstream"
