"""Ask Jev whether a query and its English description agree."""
import os

from . import dialects, words
from .caps import MAX_SQL_CHARS
from .errors import ServiceError

KEY_VAR = "TYPESAFE_API_KEY"


def _map_sdk_error(typesafe_sdk, exc):
    # Turn an SDK exception into a ServiceError by its type, never by its message.
    if isinstance(exc, typesafe_sdk.TypeSafeAuthenticationError):
        return ServiceError("bad_key", KEY_VAR)
    if isinstance(exc, typesafe_sdk.TypeSafeRateLimitError):
        return ServiceError("rate_limit")
    if isinstance(exc, typesafe_sdk.TypeSafeAPITimeoutError):
        return ServiceError("timeout")
    if isinstance(exc, typesafe_sdk.TypeSafeAPIConnectionError):
        return ServiceError("network")
    if isinstance(exc, typesafe_sdk.TypeSafeError):
        return ServiceError("upstream")
    return None


def judge(sql, english, dialect, *, environ=os.environ, client=None):
    # Return {"choice", "confidence", "probabilities", "model"} or raise ServiceError.
    label = dialects.get(dialect)["label"]
    if sql.strip() == "" or english.strip() == "":
        raise ServiceError("empty")
    if len(sql) > MAX_SQL_CHARS:
        raise ServiceError("too_long")

    try:
        import typesafe_sdk
    except ImportError:
        typesafe_sdk = None

    if client is None:
        if not environ.get(KEY_VAR):
            raise ServiceError("missing_key", KEY_VAR)
        if typesafe_sdk is None:
            raise ServiceError("internal")
        client = typesafe_sdk.TypeSafeClient(timeout=20.0)
    if typesafe_sdk is None:
        raise ServiceError("internal")

    question = typesafe_sdk.Choice(instructions=words.JUDGE_INSTRUCTIONS, criteria=words.JUDGE_CRITERIA)
    try:
        resp = client.system_one(
            {"dialect": label, "sql": sql, "english": english},
            {words.JUDGE_QUESTION: question},
        )
    except ServiceError:
        raise
    except Exception as exc:
        mapped = _map_sdk_error(typesafe_sdk, exc)
        if mapped is None:
            raise
        raise mapped from None

    answer = resp.answers.get(words.JUDGE_QUESTION)
    if answer is None or answer.choice not in words.JUDGE_CRITERIA:
        raise ServiceError("upstream")
    return {
        "choice": answer.choice,
        "confidence": float(answer.confidence),
        "probabilities": dict(answer.probabilities or {}),
        "model": resp.model,
    }
