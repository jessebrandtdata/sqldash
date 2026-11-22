import pytest

pytest.importorskip("pglast")
pytest.importorskip("sqlglot")

from sqldash.checker import check


def test_postgres_valid():
    r = check("select a from t;\nselect 2", "postgres")
    assert r == {"ok": True, "exact": True, "engine": "pglast", "statements": 2, "error": None}


def test_postgres_error_position_second_line():
    r = check("select 1;\nselect a from t where (b = 1;", "postgres")
    assert r["ok"] is False and r["exact"] is True
    assert r["error"] == {"message": 'syntax error at or near ";"', "line": 2, "col": 29, "end_col": None}


def test_postgres_position_counts_characters_not_bytes():
    assert check("select 'é', x frm t", "postgres")["error"]["col"] == 19


def test_postgres_crlf():
    e = check("select 1;\r\nselec 2", "postgres")["error"]
    assert (e["line"], e["col"]) == (2, 1)


def test_empty_and_comment_only_are_ok():
    for d in ("postgres", "mysql"):
        for sql in ("", "   -- just a comment\n"):
            r = check(sql, d)
            assert r["ok"] is True and r["statements"] == 0


def test_sqlglot_error_position():
    r = check("selec 2", "mysql")
    assert r["ok"] is False and r["exact"] is False and r["engine"] == "sqlglot"
    assert r["error"] == {"message": "Invalid expression / Unexpected token", "line": 1, "col": 7, "end_col": 8}


def test_sqlglot_error_on_second_line():
    e = check("select 1;\nselect a from t where (b = 1;", "redshift")["error"]
    assert (e["message"], e["line"], e["col"], e["end_col"]) == ("Expecting )", 2, 28, 29)


def test_sqlglot_tokenizer_error_has_no_position():
    e = check("select 'unterminated", "athena")["error"]
    assert e["message"].startswith("Error tokenizing") and e["line"] is None and e["col"] is None


def test_unknown_dialect():
    with pytest.raises(ValueError):
        check("select 1", "oracle")
