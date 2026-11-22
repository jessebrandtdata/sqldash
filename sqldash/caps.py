"""What the page may offer, given the keys in the environment."""
from .dialects import DIALECTS

MAX_SQL_CHARS = 50_000
DEFAULT_SUMMARY_MODEL = "claude-haiku-5-5"
DEFAULT_SQL_MODEL = "claude-sonnet-5-5"


def capabilities(environ) -> dict:
    has_summary = bool(environ.get("ANTHROPIC_API_KEY") or environ.get("ANTHROPIC_AUTH_TOKEN"))
    has_judge = bool(environ.get("TYPESAFE_API_KEY"))
    return {
        "dialects": DIALECTS,
        "max_sql_chars": MAX_SQL_CHARS,
        "summary": {
            "available": has_summary,
            "missing": None if has_summary else "ANTHROPIC_API_KEY",
            "model": environ.get("SQLDASH_SUMMARY_MODEL") or DEFAULT_SUMMARY_MODEL,
        },
        "sql": {
            "available": has_summary,
            "missing": None if has_summary else "ANTHROPIC_API_KEY",
            "model": environ.get("SQLDASH_SQL_MODEL") or DEFAULT_SQL_MODEL,
        },
        "judge": {
            "available": has_judge,
            "missing": None if has_judge else "TYPESAFE_API_KEY",
        },
    }
