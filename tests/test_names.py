import pytest

pytest.importorskip("sqlglot")

from sqldash import names


def read(sql, dialect="postgres"):
    # Each name as (kind, name, table, the text found at each of its spans).
    out = names.read_names(sql, dialect)
    assert out["ok"] is True
    return [(n["kind"], n["name"], n["table"], [sql[a:b] for a, b in n["spans"]]) for n in out["names"]]


def test_one_table_and_its_columns():
    sql = "SELECT name, salary FROM employees WHERE salary > 10"
    assert names.read_names(sql, "postgres") == {"ok": True, "names": [
        {"kind": "column", "name": "name", "table": "employees", "spans": [[7, 11]]},
        {"kind": "column", "name": "salary", "table": "employees", "spans": [[13, 19], [41, 47]]},
        {"kind": "table", "name": "employees", "table": None, "spans": [[25, 34]]},
    ]}


def test_schema_qualified_table_is_one_name():
    got = read("SELECT a.id FROM sales.accounts a")
    assert ("table", "sales.accounts", None, ["sales.accounts"]) in got
    assert ("column", "id", "sales.accounts", ["id"]) in got
    assert len(got) == 2


def test_cte_names_aliases_and_their_columns_are_left_out():
    sql = ("WITH top AS (SELECT dept_id, sum(salary) AS s FROM employees GROUP BY dept_id) "
           "SELECT d.name, top.s FROM top JOIN departments d ON d.id = top.dept_id")
    assert sorted(read(sql)) == sorted([
        # top.dept_id is employees.dept_id passed through unrenamed; top.s is an alias and is not
        ("column", "dept_id", "employees", ["dept_id", "dept_id", "dept_id"]),
        ("column", "salary", "employees", ["salary"]),
        ("table", "employees", None, ["employees"]),
        ("column", "name", "departments", ["name"]),
        ("table", "departments", None, ["departments"]),
        ("column", "id", "departments", ["id"]),
    ])


def test_subquery_output_columns_are_left_out():
    assert sorted(read("SELECT s.n, n FROM (SELECT name AS n FROM people) s")) == sorted([
        ("column", "name", "people", ["name"]),
        ("table", "people", None, ["people"]),
    ])


def test_unqualified_column_with_two_tables_has_no_table():
    got = read("SELECT e.name, total FROM employees e JOIN orders o ON o.emp_id = e.id")
    assert ("column", "total", None, ["total"]) in got
    assert ("column", "name", "employees", ["name"]) in got
    assert ("column", "emp_id", "orders", ["emp_id"]) in got


def test_same_column_name_under_two_tables_is_two_names():
    got = read("SELECT a.id, b.id FROM a JOIN b ON a.id = b.id")
    assert ("column", "id", "a", ["id", "id"]) in got
    assert ("column", "id", "b", ["id", "id"]) in got


def test_qualifier_that_names_the_table_is_one_of_its_positions():
    sql = "SELECT employees.salary FROM employees JOIN sales.accounts ON employees.id = accounts.emp_id"
    got = read(sql)
    assert ("table", "employees", None, ["employees", "employees", "employees"]) in got
    assert ("table", "sales.accounts", None, ["sales.accounts", "accounts"]) in got
    assert ("column", "emp_id", "sales.accounts", ["emp_id"]) in got


def test_quoted_names_keep_their_quotes():
    assert sorted(read('SELECT "Order Id", "t"."x" FROM "My Table" AS "t"')) == sorted([
        ("column", '"Order Id"', '"My Table"', ['"Order Id"']),
        ("column", '"x"', '"My Table"', ['"x"']),
        ("table", '"My Table"', None, ['"My Table"']),
    ])
    assert ("table", "`my tbl`", None, ["`my tbl`"]) in read("SELECT `my col` FROM `my tbl`", "mysql")


def test_select_alias_in_group_by_and_order_by_is_not_a_name():
    got = read("SELECT dept AS d, count(*) AS n FROM emp GROUP BY d ORDER BY n DESC")
    assert sorted(got) == sorted([("column", "dept", "emp", ["dept"]), ("table", "emp", None, ["emp"])])
    # an alias spelled like its column still counts as the column
    got = read("SELECT dept AS dept FROM emp GROUP BY dept")
    assert ("column", "dept", "emp", ["dept", "dept"]) in got


def test_correlated_subquery_resolves_the_outer_alias():
    got = read("SELECT e.name FROM employees e WHERE EXISTS "
               "(SELECT 1 FROM orders o WHERE o.emp_id = e.id AND total > 5)")
    assert ("column", "id", "employees", ["id"]) in got
    assert ("column", "total", "orders", ["total"]) in got


def test_update_delete_insert():
    assert sorted(read("UPDATE employees SET salary = salary * 1.1 WHERE dept_id = 3")) == sorted([
        ("table", "employees", None, ["employees"]),
        ("column", "salary", "employees", ["salary", "salary"]),
        ("column", "dept_id", "employees", ["dept_id"]),
    ])
    got = read("UPDATE employees e SET salary = 1 FROM depts d WHERE e.dept_id = d.id")
    assert ("column", "salary", "employees", ["salary"]) in got
    assert ("column", "id", "depts", ["id"]) in got
    assert sorted(read("DELETE FROM logs WHERE created_at < now()")) == sorted([
        ("table", "logs", None, ["logs"]),
        ("column", "created_at", "logs", ["created_at"]),
    ])
    got = read("INSERT INTO t (a, b) SELECT x, y FROM s WHERE z > 1")
    assert ("column", "a", "t", ["a"]) in got
    assert ("column", "b", "t", ["b"]) in got
    assert ("column", "x", "s", ["x"]) in got


def test_using_column_has_no_table():
    got = read("SELECT a.id, b.v FROM a JOIN b USING (id)")
    assert ("column", "id", None, ["id"]) in got
    assert ("column", "id", "a", ["id"]) in got


def test_stars_and_table_functions_are_not_names():
    assert read("SELECT *, t.* FROM t") == [("table", "t", None, ["t"])]
    assert read("SELECT g FROM generate_series(1, 3) AS g") == []


def test_positions_count_code_points():
    sql = "SELECT '\U0001F600' AS e, name FROM people"
    assert names.read_names(sql, "postgres")["names"][0] == {
        "kind": "column", "name": "name", "table": "people", "spans": [[17, 21]],
    }


def test_several_statements_share_one_text():
    got = read("SELECT 1; SELECT a FROM t")
    assert got == [("column", "a", "t", ["a"]), ("table", "t", None, ["t"])]


@pytest.mark.parametrize("dialect", ["postgres", "mysql", "redshift", "athena"])
def test_every_dialect_reads_the_same_query(dialect):
    sql = "SELECT e.name, d.title FROM employees e JOIN departments d ON d.id = e.dept_id WHERE e.salary > 100"
    got = read(sql, dialect)
    assert sorted(n for k, n, t, s in got if k == "table") == ["departments", "employees"]
    assert sorted((n, t) for k, n, t, s in got if k == "column") == [
        ("dept_id", "employees"), ("id", "departments"), ("name", "employees"),
        ("salary", "employees"), ("title", "departments"),
    ]


def test_spans_are_sorted_and_names_ordered_by_first_position():
    out = names.read_names("SELECT b, a FROM t WHERE a > b", "postgres")["names"]
    assert [n["name"] for n in out] == ["b", "a", "t"]
    assert all(n["spans"] == sorted(n["spans"]) for n in out)


def test_text_that_does_not_parse_and_empty_text():
    assert names.read_names("select (", "postgres") == {"ok": False, "names": []}
    assert names.read_names("select 'open", "mysql") == {"ok": False, "names": []}
    assert names.read_names("", "postgres") == {"ok": True, "names": []}
    assert names.read_names("  \n", "postgres") == {"ok": True, "names": []}


def test_unknown_dialect_raises():
    with pytest.raises(ValueError):
        names.read_names("select 1", "oracle")


def test_order_by_having_and_distinct_on_columns_are_positions():
    assert ("column", "salary", "employees", ["salary", "salary"]) in read(
        "SELECT name, salary FROM employees ORDER BY salary DESC LIMIT 10")
    assert ("column", "salary", "employees", ["salary", "salary"]) in read(
        "SELECT dept_id, SUM(salary) AS total FROM employees GROUP BY dept_id HAVING SUM(salary) > 1000")
    got = read("SELECT DISTINCT ON (customer_id) customer_id, created_at FROM orders "
               "ORDER BY customer_id, created_at DESC")
    assert ("column", "customer_id", "orders", ["customer_id"] * 3) in got
    assert ("column", "created_at", "orders", ["created_at"] * 2) in got
    assert ("column", "dept", "emp", ["dept", "dept"]) in read("SELECT DISTINCT dept FROM emp ORDER BY dept")


def test_window_columns_count_and_the_alias_ordered_by_does_not():
    got = read("SELECT name, RANK() OVER (PARTITION BY dept ORDER BY salary DESC) AS r FROM emp ORDER BY r")
    assert sorted(got) == sorted([
        ("column", "name", "emp", ["name"]), ("column", "dept", "emp", ["dept"]),
        ("column", "salary", "emp", ["salary"]), ("table", "emp", None, ["emp"]),
    ])


def test_unqualified_output_of_a_cte_subquery_or_function_is_not_a_name():
    sql = ("WITH t AS (SELECT dept_id, SUM(salary) AS total FROM employees GROUP BY dept_id) "
           "SELECT d.name, total FROM t JOIN departments d ON d.id = t.dept_id")
    assert "total" not in [n for k, n, t, s in read(sql)]
    sql = ("SELECT d.name, cnt, budget FROM departments d JOIN "
           "(SELECT dept_id, COUNT(*) AS cnt FROM employees GROUP BY dept_id) x ON x.dept_id = d.id")
    got = read(sql)
    assert "cnt" not in [n for k, n, t, s in got]
    # the subquery's outputs are known, so the other unqualified column is the one table's
    assert ("column", "budget", "departments", ["budget"]) in got
    assert sorted(read("SELECT u.id, tag FROM users u, unnest(u.tags) AS tag")) == sorted([
        ("column", "id", "users", ["id"]), ("column", "tags", "users", ["tags"]),
        ("table", "users", None, ["users"]),
    ])
    got = read("SELECT t.id, x FROM t CROSS JOIN UNNEST(t.arr) AS u(x)", "athena")
    assert "x" not in [n for k, n, t, s in got]


def test_update_from_a_subquery_follows_its_columns():
    got = read("UPDATE t SET a = x.b FROM (SELECT id, b FROM s) x WHERE t.id = x.id")
    # x.b and x.id are s's columns passed through unrenamed, so they are positions of those
    assert sorted(got) == sorted([
        ("table", "t", None, ["t", "t"]), ("column", "a", "t", ["a"]), ("column", "id", "t", ["id"]),
        ("column", "id", "s", ["id", "id"]), ("column", "b", "s", ["b", "b"]), ("table", "s", None, ["s"]),
    ])


def test_upsert_excluded_is_the_target_column():
    got = read("INSERT INTO counts (k, n) VALUES ('a', 1) ON CONFLICT (k) DO UPDATE SET n = EXCLUDED.n")
    assert sorted(got) == sorted([
        ("table", "counts", None, ["counts"]),
        ("column", "k", "counts", ["k", "k"]),
        ("column", "n", "counts", ["n", "n", "n"]),
    ])


def test_merge_keeps_target_and_source_columns_apart():
    sql = ("MERGE INTO target t USING source s ON t.id = s.id "
           "WHEN MATCHED THEN UPDATE SET val = s.val "
           "WHEN NOT MATCHED THEN INSERT (id, val) VALUES (s.id, s.val)")
    assert sorted(read(sql)) == sorted([
        ("table", "target", None, ["target"]), ("table", "source", None, ["source"]),
        ("column", "id", "target", ["id", "id"]), ("column", "id", "source", ["id", "id"]),
        ("column", "val", "target", ["val", "val"]), ("column", "val", "source", ["val", "val"]),
    ])


def test_a_cte_named_like_its_table_does_not_hide_the_table():
    got = read("WITH orders AS (SELECT id, total FROM orders WHERE total > 0) SELECT o.id FROM orders o")
    assert sorted(got) == sorted([
        ("table", "orders", None, ["orders"]),
        ("column", "id", "orders", ["id", "id"]), ("column", "total", "orders", ["total", "total"]),
    ])


def test_unquoted_qualifier_matches_the_table_without_regard_to_case():
    got = read("SELECT employees.id FROM Employees")
    assert sorted(got) == sorted([
        ("table", "Employees", None, ["employees", "Employees"]), ("column", "id", "Employees", ["id"]),
    ])


def test_text_nested_too_deeply_is_not_read():
    sql = "SELECT " + "(" * 3000 + "1" + ")" * 3000
    assert names.read_names(sql, "postgres") == {"ok": False, "names": []}


def test_a_column_passed_through_a_cte_keeps_all_its_positions():
    sql = ("WITH ranked AS (SELECT name, dept_id, salary, ROW_NUMBER() OVER "
           "(PARTITION BY dept_id ORDER BY salary DESC) AS rn FROM employees) "
           "SELECT name, r.dept_id, salary FROM ranked r WHERE rn = 1 ORDER BY dept_id")
    assert sorted(read(sql)) == sorted([
        ("column", "name", "employees", ["name", "name"]),
        ("column", "dept_id", "employees", ["dept_id"] * 4),
        ("column", "salary", "employees", ["salary"] * 3),
        ("table", "employees", None, ["employees"]),
    ])


def test_a_renamed_output_is_still_not_a_name():
    sql = "WITH t AS (SELECT salary AS pay, id FROM employees) SELECT pay, id FROM t ORDER BY pay"
    assert sorted(read(sql)) == sorted([
        ("column", "salary", "employees", ["salary"]), ("column", "id", "employees", ["id", "id"]),
        ("table", "employees", None, ["employees"]),
    ])


def test_star_from_one_table_passes_every_column_through():
    sql = "WITH recent AS (SELECT * FROM orders WHERE created_at > now()) SELECT id, r.total FROM recent r"
    assert sorted(read(sql)) == sorted([
        ("table", "orders", None, ["orders"]), ("column", "created_at", "orders", ["created_at"]),
        ("column", "id", "orders", ["id"]), ("column", "total", "orders", ["total"]),
    ])
    # with a second source beside the starred subquery, an unqualified name could be either's: no box
    got = read("SELECT x, d.y FROM (SELECT * FROM a) s JOIN d ON d.k = s.k")
    assert "x" not in [n for k, n, t, s in got]
    assert ("column", "k", "a", ["k"]) in got


def test_order_by_after_a_union_follows_the_left_branch():
    got = read("SELECT name FROM employees UNION SELECT name FROM contractors ORDER BY name")
    assert sorted(got) == sorted([
        ("column", "name", "employees", ["name", "name"]), ("table", "employees", None, ["employees"]),
        ("column", "name", "contractors", ["name"]), ("table", "contractors", None, ["contractors"]),
    ])


def test_delete_using_a_cte_follows_its_columns():
    got = read("WITH old AS (SELECT id FROM logs WHERE ts < now()) DELETE FROM logs USING old WHERE logs.id = old.id")
    assert sorted(got) == sorted([
        ("table", "logs", None, ["logs", "logs", "logs"]),
        ("column", "id", "logs", ["id", "id", "id"]), ("column", "ts", "logs", ["ts"]),
    ])


def test_an_alias_beside_a_star_is_not_passed_through():
    sql = ("WITH x AS (SELECT *, ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY created_at DESC) AS rn "
           "FROM orders) SELECT id, rn FROM x WHERE rn = 1")
    assert sorted(read(sql)) == sorted([
        ("column", "customer_id", "orders", ["customer_id"]), ("column", "created_at", "orders", ["created_at"]),
        ("table", "orders", None, ["orders"]), ("column", "id", "orders", ["id"]),
    ])
    got = read("WITH x AS (SELECT *, salary * 2 AS pay2 FROM emp) SELECT name, pay2 FROM x ORDER BY pay2")
    assert "pay2" not in [n for k, n, t, s in got]
    assert ("column", "name", "emp", ["name"]) in got


def test_order_by_reads_a_select_alias_before_a_column_of_the_same_name():
    got = read("SELECT dept, SUM(amount) AS amount FROM sales GROUP BY dept ORDER BY amount DESC")
    assert ("column", "amount", "sales", ["amount"]) in got
    assert ("column", "dept", "sales", ["dept", "dept"]) in got
    assert ("column", "salary", "emp", ["salary"]) in read("SELECT -salary AS salary FROM emp ORDER BY salary")
    # GROUP BY reads the column first
    got = read("SELECT lower(city) AS city, count(*) FROM shops GROUP BY city")
    assert ("column", "city", "shops", ["city", "city"]) in got


def test_a_column_with_no_stated_table_is_followed_out_of_a_cte():
    sql = ("WITH j AS (SELECT name, total FROM emp e JOIN orders o ON o.emp_id = e.id) "
           "SELECT name, SUM(total) FROM j GROUP BY name")
    got = read(sql)
    assert ("column", "name", None, ["name", "name", "name"]) in got
    assert ("column", "total", None, ["total", "total"]) in got


def test_recursive_cte_follows_its_own_column():
    sql = ("WITH RECURSIVE t AS (SELECT id, parent_id FROM nodes WHERE id = 1 UNION ALL "
           "SELECT n.id, n.parent_id FROM nodes n JOIN t ON n.parent_id = t.id) SELECT id FROM t")
    assert sorted(read(sql)) == sorted([
        ("column", "id", "nodes", ["id"] * 5), ("column", "parent_id", "nodes", ["parent_id"] * 3),
        ("table", "nodes", None, ["nodes", "nodes"]),
    ])
