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
    from sqlglot.optimizer.scope import Scope, traverse_scope

    try:
        trees = [t for t in sqlglot.parse(sql, read=dialect) if t is not None]
        return {"ok": True, "names": _names_in(sql, trees, exp, Scope, traverse_scope)}
    except (ParseError, TokenError, RecursionError):
        # text sqlglot cannot parse, or nested too deeply to walk
        return {"ok": False, "names": []}


def _names_in(sql, trees, exp, Scope, traverse_scope):
    found = {}  # (kind, owning table, name) -> spans

    def add(kind, table, span, name=None):
        # Record one occurrence; the name is the text at the span unless one is given.
        if span is not None:
            found.setdefault((kind, table, name or sql[span[0]:span[1]]), []).append(span)

    statements = (exp.Select, exp.Update, exp.Delete, exp.Insert, exp.Merge)

    for tree in trees:
        scopes = list(traverse_scope(tree))
        # a Table node a scope lists as its own source is a real table, whatever it is called
        scoped = {id(v) for sc in scopes for v in sc.sources.values() if isinstance(v, exp.Table)}
        cte_by_name = {c.alias: c for c in tree.find_all(exp.CTE)}
        cte_names = set(cte_by_name)
        table_name = {}  # id(Table node) -> the table's name as the SQL spells it
        derived = set(cte_names)  # lower-cased names that qualify something other than a real table
        for t in tree.find_all(exp.Table):
            # a table function has no identifier; an unqualified reference to a CTE is not a table
            is_cte = t.name in cte_names and not t.args.get("db") and id(t) not in scoped
            if not isinstance(t.this, exp.Identifier) or is_cte:
                derived.add(t.alias or t.name)
                continue
            span = _joined([t.args.get(k) for k in ("catalog", "db", "this")])
            if span is not None:
                table_name[id(t)] = sql[span[0]:span[1]]
                add("table", None, span)
        derived.update(n.alias for n in tree.find_all(exp.Subquery, exp.Unnest, exp.Lateral) if n.alias)
        derived = {d.lower() for d in derived}

        done = set()  # id(Column node) for every column already settled
        by_query = {id(sc.expression): sc for sc in scopes}  # id(query node) -> its scope
        settled = {}  # id(Column node) -> (table, name) of the real column it turned out to be
        passed = {}  # id(query node) -> {output name: (table, name)} for columns it selects unrenamed
        starred = set()  # id(query node) for every query that selects a bare *

        def through(scope, name, star=True):
            # The real (table, name) behind an output column of a subquery or CTE, or None.
            query = scope.expression
            if isinstance(query, exp.SetOperation):
                # a UNION gives out its left branch's names
                left = by_query.get(id(query.left.unnest()))
                return through(left, name, star) if left is not None else None
            hit = passed.get(id(query), {}).get(name)
            if hit is not None:
                return hit
            if name in getattr(query, "named_selects", []):
                # the query gives this name out itself, as an alias or an expression: not a table's column
                return None
            picked = [src for _, src in scope.selected_sources.values()]
            if not star or id(query) not in starred or len(picked) != 1:
                return None
            src = picked[0]
            if id(src) in table_name:
                # SELECT * FROM one table: every other name it gives out is that table's column
                return (table_name[id(src)], None)
            return through(src, name) if isinstance(src, Scope) else None

        def keep(col, table, name=None):
            # Record a column occurrence under its real table and remember what it resolved to.
            span = _span(col.this)
            if span is not None:
                add("column", table, span, name)
                settled[id(col)] = (table, name or sql[span[0]:span[1]])

        def lookup(sources, col):
            # The source a qualifier names; an unquoted qualifier matches without regard to case.
            src = sources.get(col.table)
            ident = col.args.get("table")
            if src is None and not getattr(ident, "quoted", False):
                want = col.table.lower()
                src = next((v for k, v in sources.items() if k.lower() == want), None)
            return src

        def outputs(key, src):
            # The column names a derived source is known to give out, or None when they cannot be told.
            if isinstance(src, Scope):
                named = list(getattr(src.expression, "named_selects", []))
                if not named or "*" in named:
                    # UNNEST(...) AS tag gives one column called by its alias; otherwise unknown
                    return {key} if isinstance(src.expression, exp.Unnest) and not named else None
                return set(named) | {key}
            return None

        def claim(col, sources, aliases=frozenset(), plain=frozenset(), owner=None, ordering=False):
            # Settle one column against the sources of one part of the query, if they resolve it.
            if id(col) in done or not isinstance(col.this, exp.Identifier):
                return
            if not col.table and col.name in aliases and (ordering or col.name not in plain):
                # a select alias: ORDER BY and DISTINCT ON read the alias first; GROUP BY and HAVING
                # read it only when no column of that name is selected
                done.add(id(col))
                return
            real = [s for s in sources.values() if id(s) in table_name]
            if col.table:
                src = lookup(sources, col)
                if src is None:
                    return
                done.add(id(col))
                if isinstance(src, Scope):
                    # x.total where x is a subquery or CTE: a position only if x passes a real column through
                    hit = through(src, col.name)
                    if hit is not None:
                        keep(col, *hit)
                    return
                if id(src) not in table_name:
                    return
                if not src.alias:
                    # the qualifier names the table itself, so it is one of the table's positions
                    add("table", None, _joined([col.args.get(k) for k in ("catalog", "db", "table")]),
                        table_name[id(src)])
                keep(col, table_name[id(src)])
                return
            done.add(id(col))
            if owner is not None:
                keep(col, owner)
                return
            others = [(k, s) for k, s in sources.items() if id(s) not in table_name]
            for key, src in others:
                # a real column a subquery or CTE passes through; a bare * counts only when it is the sole source
                hit = through(src, col.name, star=len(sources) == 1) if isinstance(src, Scope) else None
                if hit is not None:
                    keep(col, *hit)
                    return
            for key, src in others:
                given = outputs(key, src)
                if given is None or col.name in given:
                    # it comes out of a subquery, CTE or function, or might: not a table's column
                    return
            if len(real) == 1:
                keep(col, table_name[id(real[0])])
            elif real:
                keep(col, None)

        def clause(col, root):
            # "order" in the query's own ORDER BY or DISTINCT ON, "group" in GROUP BY, HAVING or QUALIFY, else None.
            node = col.parent
            while node is not None and node is not root:
                if isinstance(node, (exp.Group, exp.Having, exp.Qualify)):
                    return "group"
                if isinstance(node, exp.Distinct):
                    return "order"
                if isinstance(node, exp.Order) and not isinstance(node.parent, exp.Window):
                    return "order"
                node = node.parent
            return None

        # traverse_scope yields inner queries first, so a column settles in its innermost query
        for scope in scopes:
            # every column written in this query, then the outer references of its subqueries
            own = list(scope.find_all(exp.Column))
            selects = getattr(scope.expression, "selects", [])
            aliases = frozenset(e.alias for e in selects if isinstance(e, exp.Alias))
            where = {id(c): clause(c, scope.expression) for c in own}
            plain = frozenset(c.name for c in own if not c.table and where[id(c)] is None)
            if isinstance(scope.expression, exp.SetOperation):
                # ORDER BY after a UNION names the union's outputs
                for col in own:
                    hit = through(scope, col.name) if not col.table and isinstance(col.this, exp.Identifier) else None
                    done.add(id(col))
                    if hit is not None:
                        keep(col, *hit)
                continue
            # only what this query's FROM and JOINs name; scope.sources also lists every visible CTE
            sources = {name: src for name, (_, src) in scope.selected_sources.items()}
            for col in own + list(scope.columns):
                claim(col, sources, aliases, plain, ordering=where.get(id(col)) == "order")
            # what this query gives out under a real column's own name, for the queries that read it
            passed[id(scope.expression)] = {
                e.name: settled[id(e)] for e in selects if isinstance(e, exp.Column) and id(e) in settled
            }
            if any(isinstance(e, exp.Star) for e in selects):
                starred.add(id(scope.expression))

        # UPDATE, DELETE, INSERT and MERGE have no scope of their own
        for stmt in tree.find_all(exp.Update, exp.Delete, exp.Insert, exp.Merge):
            if not isinstance(stmt, exp.Merge) and stmt.find_ancestor(exp.Merge) is not None:
                # the UPDATE and INSERT arms of a MERGE are handled with their MERGE
                continue
            target = stmt.this.this if isinstance(stmt.this, exp.Schema) else stmt.this
            target_name = table_name.get(id(target))
            sources = {
                t.alias or t.name: t for t in stmt.find_all(exp.Table) if t.find_ancestor(*statements) is stmt
            }
            for name, t in list(sources.items()):
                # a CTE this statement reads is a derived source, like in a SELECT
                cte = cte_by_name.get(t.name) if id(t) not in table_name else None
                if cte is not None and id(cte.this) in by_query:
                    sources[name] = by_query[id(cte.this)]
            for sub in stmt.find_all(exp.Subquery):
                # FROM (SELECT ...) x directly under this statement
                if sub.alias and sub.find_ancestor(*statements) is stmt and id(sub.this) in by_query:
                    sources[sub.alias] = by_query[id(sub.this)]
            assigned, listed = list(stmt.expressions) if isinstance(stmt, exp.Update) else [], []
            if isinstance(stmt.this, exp.Schema):
                # INSERT INTO t (a, b): the listed columns are t's
                listed += stmt.this.expressions
            conflict = stmt.args.get("conflict") if isinstance(stmt, exp.Insert) else None
            if conflict is not None:
                # ON CONFLICT ... DO UPDATE SET a = ...: the assigned column is t's
                assigned += conflict.expressions
            if isinstance(stmt, exp.Merge):
                for when in stmt.find_all(exp.When):
                    then = when.args.get("then")
                    if isinstance(then, exp.Update):
                        assigned += then.expressions
                    elif isinstance(then, exp.Insert) and isinstance(then.this, exp.Tuple):
                        listed += then.this.expressions
            if target_name is not None:
                for item in listed:
                    ident = item.this if isinstance(item, exp.Column) and not item.table else item
                    if isinstance(ident, exp.Identifier):
                        add("column", target_name, _span(ident))
                        done.add(id(item))
                for eq in assigned:
                    # UPDATE t SET a = ...: the assigned column is t's
                    if isinstance(eq, exp.EQ) and isinstance(eq.this, exp.Column) and not eq.this.table:
                        claim(eq.this, sources, owner=target_name)
                if conflict is not None:
                    for col in stmt.find_all(exp.Column):
                        ident = col.args.get("table")
                        # EXCLUDED.a is the row that was to be inserted: a is t's column
                        if col.table.lower() == "excluded" and not getattr(ident, "quoted", False) \
                                and isinstance(col.this, exp.Identifier) and id(col) not in done:
                            add("column", target_name, _span(col.this))
                            done.add(id(col))
            for col in stmt.find_all(exp.Column):
                claim(col, sources)

        for col in tree.find_all(exp.Column):
            # a qualifier nothing resolved and nothing derived: the column is real, its table is not stated
            if id(col) not in done and col.table and col.table.lower() not in derived \
                    and isinstance(col.this, exp.Identifier):
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
    return names
