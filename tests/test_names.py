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
        ("column", "dept_id", "employees", ["dept_id", "dept_id"]),
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
