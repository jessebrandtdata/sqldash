import json

from sqldash.caps import capabilities


def test_caps_without_keys():
    c = capabilities({})
    assert c["summary"] == {"available": False, "missing": "ANTHROPIC_API_KEY", "model": "claude-haiku-5-5"}
    assert c["judge"] == {"available": False, "missing": "TYPESAFE_API_KEY"}
    assert [d["id"] for d in c["dialects"]] == ["postgres", "mysql", "redshift", "athena"]


def test_caps_with_keys_never_echo_them():
    c = capabilities({"ANTHROPIC_API_KEY": "sk-secret", "TYPESAFE_API_KEY": "ts-secret", "SQLDASH_SUMMARY_MODEL": "claude-sonnet-5-5"})
    assert c["summary"] == {"available": True, "missing": None, "model": "claude-sonnet-5-5"}
    assert "secret" not in json.dumps(c)


def test_caps_sql_entry():
    assert capabilities({})["sql"] == {"available": False, "missing": "ANTHROPIC_API_KEY", "model": "claude-sonnet-5-5"}
    c = capabilities({"ANTHROPIC_AUTH_TOKEN": "tok-secret", "SQLDASH_SQL_MODEL": "claude-haiku-5-5"})
    assert c["sql"] == {"available": True, "missing": None, "model": "claude-haiku-5-5"}
    assert "secret" not in json.dumps(c)
