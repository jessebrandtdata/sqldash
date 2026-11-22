"""Ask Claude to explain a query in English."""
import os

from . import dialects, words
from .caps import DEFAULT_SUMMARY_MODEL, MAX_SQL_CHARS
from .errors import ServiceError

KEY_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")


def map_sdk_error(anthropic, exc):
    # Turn an SDK exception into a ServiceError by its type, never by its message.
    if isinstance(exc, anthropic.AuthenticationError):
        return ServiceError("bad_key", "ANTHROPIC_API_KEY")
    if isinstance(exc, anthropic.RateLimitError):
        return ServiceError("rate_limit")
    if isinstance(exc, anthropic.APITimeoutError):
        return ServiceError("timeout")
    if isinstance(exc, anthropic.APIConnectionError):
        return ServiceError("network")
    if isinstance(exc, anthropic.APIError):
        return ServiceError("upstream")
    return None


def summarize(sql, dialect, *, environ=os.environ, client=None):
    # Return {"text", "model", "input_tokens", "output_tokens"} or raise ServiceError.
    label = dialects.get(dialect)["label"]
    if sql.strip() == "":
        raise ServiceError("empty")
    if len(sql) > MAX_SQL_CHARS:
        raise ServiceError("too_long")

    try:
        import anthropic
    except ImportError:
        anthropic = None

    if client is None:
        if not any(environ.get(name) for name in KEY_VARS):
            raise ServiceError("missing_key", "ANTHROPIC_API_KEY")
        if anthropic is None:
            raise ServiceError("internal")
        client = anthropic.Anthropic(timeout=30.0, max_retries=1)

    model = environ.get("SQLDASH_SUMMARY_MODEL") or DEFAULT_SUMMARY_MODEL
    try:
        response = client.messages.create(
            model=model,
            max_tokens=4000,
            system=words.SUMMARY_SYSTEM.format(dialect=label),
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": words.summary_user(label, sql)}],
        )
    except ServiceError:
        raise
    except Exception as exc:
        mapped = map_sdk_error(anthropic, exc) if anthropic is not None else None
        if mapped is None:
            raise
        raise mapped from None

    if response.stop_reason == "refusal":
        raise ServiceError("refusal")
    if response.stop_reason == "max_tokens":
        raise ServiceError("cut_off")
    text = "\n".join(b.text for b in response.content if b.type == "text")
    if text == "":
        raise ServiceError("upstream")
    return {
        "text": text,
        "model": response.model,
        "input_tokens": response.usage.input_tokens or 0,
        "output_tokens": response.usage.output_tokens or 0,
    }
