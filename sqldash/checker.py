from sqldash import dialects


def _result(d, statements, error):
    # Build the result dict shared by both engines.
    return {"ok": error is None, "exact": d["exact"], "engine": d["engine"],
            "statements": statements, "error": error}


def _line_col(sql, index):
    # Turn a 0-based character index into a 1-based (line, col); a \r before \n stays on its line.
    before = sql[:index]
    line = before.count("\n") + 1
    col = index - (before.rfind("\n") + 1) + 1
    return line, col


def _check_postgres(sql, d):
    # Parse with the PostgreSQL grammar and report the error index as line and column.
    import pglast
    from pglast.parser import ParseError
    try:
        stmts = pglast.parse_sql(sql)
    except ParseError as e:
        message, index = e.args[0], e.args[1]
        if index is None:
            # an end-of-input error sits just after the last non-whitespace character
            kept = sql.rstrip()
            line, col = _line_col(sql, len(kept)) if kept else (None, None)
        else:
            line, col = _line_col(sql, index)
        return _result(d, 0, {"message": message, "line": line, "col": col, "end_col": None})
    return _result(d, len(stmts), None)


def _check_sqlglot(sql, d):
    # Parse with sqlglot in the dialect and report the first error with its span.
    import sqlglot
    from sqlglot.errors import ParseError, TokenError
    try:
        stmts = sqlglot.parse(sql, read=d["id"])
    except ParseError as e:
        first = e.errors[0]
        line, last = first.get("line"), first.get("col")
        if line is None or last is None:
            return _result(d, 0, {"message": first["description"], "line": None, "col": None, "end_col": None})
        start = last - len(first.get("highlight") or "") + 1
        return _result(d, 0, {"message": first["description"], "line": line, "col": start, "end_col": last + 1})
    except TokenError as e:
        return _result(d, 0, {"message": str(e), "line": None, "col": None, "end_col": None})
    return _result(d, sum(1 for s in stmts if s is not None), None)


def check(sql, dialect):
    # Check the SQL's syntax in the dialect; raises ValueError on an unknown dialect.
    d = dialects.get(dialect)
    if d["engine"] == "pglast":
        return _check_postgres(sql, d)
    return _check_sqlglot(sql, d)
