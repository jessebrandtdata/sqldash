"""Read the table and column names a query uses, with where each one sits in the text."""
from . import dialects


def _span(node):
    # The [start, end) of an identifier in code points, or None when the parser kept no position.
    meta = getattr(node, "meta", None) or {}
    if "start" not in meta or "end" not in meta:
        return None
    return [meta["start"], meta["end"] + 1]


def _joined(nodes):
    # One span from the first identifier's start to the last one's end, or None if any lacks a position.
    spans = [_span(n) for n in nodes if n is not None]
    if not spans or any(s is None for s in spans):
        return None
    return [spans[0][0], spans[-1][1]]


def read_names(sql, dialect):
    # Return {"ok", "names"}; raises ValueError on an unknown dialect.
    dialects.get(dialect)
    import sqlglot
    from sqlglot import exp
    from sqlglot.errors import ParseError, TokenError
    from sqlglot.optimizer.scope import traverse_scope

    try:
        trees = [t for t in sqlglot.parse(sql, read=dialect) if t is not None]
    except (ParseError, TokenError):
        return {"ok": False, "names": []}

    found = {}  # (kind, owning table, name) -> spans

    def add(kind, table, span, name=None):
        # Record one occurrence; the name is the text at the span unless one is given.
        if span is not None:
            found.setdefault((kind, table, name or sql[span[0]:span[1]]), []).append(span)

    statements = (exp.Select, exp.Update, exp.Delete, exp.Insert)
    late_clauses = (exp.Group, exp.Order, exp.Having, exp.Qualify)

    for tree in trees:
        cte_names = {c.alias for c in tree.find_all(exp.CTE)}
        table_name = {}  # id(Table node) -> the table's name as the SQL spells it
        for t in tree.find_all(exp.Table):
            # a table function has no identifier; an unqualified CTE name is not a table
            if not isinstance(t.this, exp.Identifier) or (t.name in cte_names and not t.args.get("db")):
                continue
            span = _joined([t.args.get(k) for k in ("catalog", "db", "this")])
            if span is not None:
                table_name[id(t)] = sql[span[0]:span[1]]
                add("table", None, span)

        done = set()  # id(Column node) for every column already settled

        def claim(col, sources, aliases=frozenset(), plain=frozenset(), owner=None):
            # Settle one column against the sources of one part of the query, if they resolve it.
            if id(col) in done or not isinstance(col.this, exp.Identifier):
                return
            if not col.table and col.name in aliases and col.name not in plain:
                # a select alias used in GROUP BY, ORDER BY or HAVING
                done.add(id(col))
                return
            real = [s for s in sources.values() if id(s) in table_name]
            if col.table:
                src = sources.get(col.table)
                if src is None:
                    return
                done.add(id(col))
                if id(src) not in table_name:
                    return
                if not src.alias:
                    # the qualifier names the table itself, so it is one of the table's positions
                    add("table", None, _joined([col.args.get(k) for k in ("catalog", "db", "table")]),
                        table_name[id(src)])
                add("column", table_name[id(src)], _span(col.this))
                return
            done.add(id(col))
            if owner is not None:
                add("column", owner, _span(col.this))
            elif len(sources) == 1:
                if real:
                    add("column", table_name[id(real[0])], _span(col.this))
            elif real:
                add("column", None, _span(col.this))

        # traverse_scope yields inner queries first, so a column settles in its innermost query
        for scope in traverse_scope(tree):
            selects = getattr(scope.expression, "selects", [])
            aliases = frozenset(e.alias for e in selects if isinstance(e, exp.Alias))
            plain = frozenset(
                c.name for c in scope.columns if not c.table and not c.find_ancestor(*late_clauses)
            )
            for col in scope.columns:
                claim(col, scope.sources, aliases, plain)

        # UPDATE, DELETE and INSERT have no scope of their own
        for stmt in tree.find_all(exp.Update, exp.Delete, exp.Insert):
            target = stmt.this.this if isinstance(stmt.this, exp.Schema) else stmt.this
            target_name = table_name.get(id(target))
            sources = {
                t.alias or t.name: t for t in stmt.find_all(exp.Table) if t.find_ancestor(*statements) is stmt
            }
            if isinstance(stmt.this, exp.Schema) and target_name is not None:
                # INSERT INTO t (a, b): the listed columns are t's
                for ident in stmt.this.expressions:
                    if isinstance(ident, exp.Identifier):
                        add("column", target_name, _span(ident))
            if isinstance(stmt, exp.Update) and target_name is not None:
                # UPDATE t SET a = ...: the assigned column is t's
                for eq in stmt.expressions:
                    if isinstance(eq, exp.EQ) and isinstance(eq.this, exp.Column) and not eq.this.table:
                        claim(eq.this, sources, owner=target_name)
            for col in stmt.find_all(exp.Column):
                claim(col, sources)

        for col in tree.find_all(exp.Column):
            # a qualifier nothing resolved: the column is real, its table is not stated
            if id(col) not in done and col.table and isinstance(col.this, exp.Identifier):
                add("column", None, _span(col.this))
        for join in tree.find_all(exp.Join):
            # JOIN ... USING (id): a column of both sides
            for ident in join.args.get("using") or []:
                if isinstance(ident, exp.Identifier):
                    add("column", None, _span(ident))

    names = [
        {"kind": kind, "name": name, "table": table, "spans": sorted(spans)}
        for (kind, table, name), spans in found.items()
    ]
    names.sort(key=lambda n: n["spans"][0])
    return {"ok": True, "names": names}
