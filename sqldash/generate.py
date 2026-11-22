"""Ask Claude to write a query from an English description."""
import json
import os

from . import dialects, words
from .caps import DEFAULT_SQL_MODEL, MAX_SQL_CHARS
from .errors import ServiceError
from .summary import KEY_VARS, map_sdk_error

SQL_FORMAT = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {"sql": {"type": "string"}, "note": {"type": "string"}},
        "required": ["sql", "note"],
        "additionalProperties": False,
    },
}


def generate(english, dialect, *, environ=os.environ, client=None):
    # Return {"sql", "note", "model", "input_tokens", "output_tokens"} or raise ServiceError.
    label = dialects.get(dialect)["label"]
    if english.strip() == "":
        raise ServiceError("empty")
    if len(english) > MAX_SQL_CHARS:
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

    model = environ.get("SQLDASH_SQL_MODEL") or DEFAULT_SQL_MODEL
    try:
        response = client.messages.create(
            model=model,
            max_tokens=8000,
            system=words.SQL_SYSTEM.format(dialect=label),
            output_config={"effort": "low", "format": SQL_FORMAT},
            messages=[{"role": "user", "content": words.sql_user(label, english)}],
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
    text = next((b.text for b in response.content if b.type == "text"), None)
    if text is None:
        raise ServiceError("upstream")
    try:
        data = json.loads(text)
    except ValueError:
        raise ServiceError("upstream") from None
    if not isinstance(data, dict) or not isinstance(data.get("sql"), str) or not isinstance(data.get("note"), str):
        raise ServiceError("upstream")
    sql = data["sql"].strip().replace("\r\n", "\n").replace("\r", "\n")
    note = data["note"].strip()
    if sql == "" and note == "":
        raise ServiceError("upstream")
    return {
        "sql": sql,
        "note": note,
        "model": response.model,
        "input_tokens": response.usage.input_tokens or 0,
        "output_tokens": response.usage.output_tokens or 0,
    }
