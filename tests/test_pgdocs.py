"""Tests for the docs index builder and the committed docs files (no network)."""
import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX_PATH = ROOT / "web" / "public" / "docs" / "pg17.json"
LINKS_PATH = ROOT / "web" / "public" / "docs" / "links.json"
SCRIPT = ROOT / "scripts" / "build_pgdocs.py"

BASE = "https://www.postgresql.org/docs/17/"


def load_script():
    # import the build script by path; importing must not touch the network
    spec = importlib.util.spec_from_file_location("build_pgdocs", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def committed(path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"entries": {}, "reserved": {}}


INDEX = committed(INDEX_PATH)
LINKS = json.loads(LINKS_PATH.read_text(encoding="utf-8")) if LINKS_PATH.exists() else {}

REF_PAGE = """
<refentry id="SQL-ABORT">
 <indexterm zone="sql-abort"><primary>ABORT</primary></indexterm>
 <refnamediv>
  <refname>ABORT</refname>
  <refpurpose>abort the current transaction</refpurpose>
 </refnamediv>
 <refsynopsisdiv>
<synopsis>
ABORT [ WORK | TRANSACTION ]
      [ AND [ NO ] CHAIN ]
</synopsis>
 </refsynopsisdiv>
 <refsect1>
  <title>Description</title>
  <para>
   <command>ABORT</command> rolls back the
   current transaction &mdash; all updates
   are discarded when <literal>x &lt; y</literal> on &productname;.
  </para>
  <para>Second paragraph.</para>
 </refsect1>
 <refsect1>
  <title>Parameters</title>
  <refsect2 id="sql-abort-clause" xreflabel="WORK Clause">
   <title>WORK Clause</title>
   <para>One short paragraph.</para>
  </refsect2>
 </refsect1>
</refentry>
"""

FUNC_ROWS = """
<sect1 id="functions-math">
 <table id="t">
  <tbody>
   <row>
    <entry role="func_table_entry"><para role="func_signature">
     <function>round</function> ( <type>numeric</type> )
     <returnvalue>numeric</returnvalue>
    </para>
    <para>
     Rounds to <literal>0</literal> places.
    </para>
    <para><literal>round(42.4)</literal> <returnvalue>42</returnvalue></para></entry>
   </row>
   <row>
    <entry role="func_table_entry"><para role="func_signature">
     <replaceable>a</replaceable> <literal>+</literal> <replaceable>b</replaceable>
     <returnvalue>x</returnvalue>
    </para>
    <para>An operator row.</para></entry>
   </row>
  </tbody>
 </table>
</sect1>
"""

LITERAL_SECTIONS = """
<sect1 id="functions-conditional">
 <sect2 id="functions-coalesce-nvl-ifnull">
  <title><literal>COALESCE</literal></title>
  <indexterm><primary>NVL</primary></indexterm>
<synopsis>
<function>COALESCE</function>(<replaceable>value</replaceable> <optional>, ...</optional>)
</synopsis>
  <para>The <function>COALESCE</function> function returns the first non-null argument.</para>
  <para>Second paragraph.</para>
 </sect2>
 <sect2 id="functions-other">
  <title>Something else</title>
  <para>Not wanted.</para>
 </sect2>
</sect1>
"""

KWLIST = """
PG_KEYWORD("abort", ABORT_P, UNRESERVED_KEYWORD, BARE_LABEL)
PG_KEYWORD("select", SELECT, RESERVED_KEYWORD, BARE_LABEL)
PG_KEYWORD("coalesce", COALESCE, COL_NAME_KEYWORD, BARE_LABEL)
PG_KEYWORD("left", LEFT, TYPE_FUNC_NAME_KEYWORD, BARE_LABEL)
"""


def test_importing_the_script_does_not_fetch():
    assert hasattr(load_script(), "main")


def test_parse_ref_page_command_and_clause():
    mod = load_script()
    rows = mod.parse_ref_page(REF_PAGE)
    cmd = [r for r in rows if r["kind"] == "command"][0]
    assert cmd["key"] == "ABORT"
    assert cmd["url"] == BASE + "sql-abort.html"
    assert cmd["synopsis"] == "ABORT [ WORK | TRANSACTION ]\n      [ AND [ NO ] CHAIN ]"
    assert cmd["text"].startswith("abort the current transaction")
    assert "rolls back the current transaction — all updates are discarded when x < y on PostgreSQL." in cmd["text"]
    assert "Second paragraph" not in cmd["text"]
    clause = [r for r in rows if r["kind"] == "clause"][0]
    assert clause["key"] == "WORK"
    assert clause["url"] == BASE + "sql-abort.html#SQL-ABORT-CLAUSE"
    assert clause["text"] == "One short paragraph."


def test_parse_func_rows_keeps_signature_and_skips_operators():
    rows = load_script().parse_func_rows(FUNC_ROWS)
    assert [r["key"] for r in rows] == ["ROUND"]
    row = rows[0]
    assert row["kind"] == "function"
    assert row["synopsis"] == "round ( numeric ) numeric"
    assert row["text"] == "Rounds to 0 places."
    assert row["url"] == BASE + "functions-math.html"


def test_parse_literal_sections():
    rows = load_script().parse_literal_sections(LITERAL_SECTIONS, "function")
    assert [r["key"] for r in rows] == ["COALESCE"]
    row = rows[0]
    assert row["url"] == BASE + "functions-conditional.html"
    assert row["synopsis"] == "COALESCE(value , ...)"
    assert row["text"] == (
        "The COALESCE function returns the first non-null argument. Second paragraph."
    )


CODE_IN_PARA = """
<sect1 id="queries-x"><sect2 id="queries-group">
 <title><literal>GROUP BY</literal> Clause</title>
 <para>
  The clause has the general form
<synopsis>
GROUP BY a,
         b &lt; c
</synopsis>
  and then <literal>GROUP BY</literal> condenses rows. One of
  <itemizedlist>
   <listitem><para>first</para></listitem>
   <listitem><para>second   item</para></listitem>
  </itemizedlist>
  applies.
 </para>
</sect2></sect1>
"""

TYPE_TABLE = """
<chapter id="datatype"><table id="datatype-table">
 <thead><row><entry>Name</entry><entry>Aliases</entry><entry>Description</entry></row></thead>
 <tbody>
  <row><entry><type>integer</type></entry><entry><type>int</type>, <type>int4</type></entry>
   <entry>signed four-byte integer</entry></row>
  <row><entry><type>box</type></entry><entry></entry><entry>rectangular box</entry></row>
 </tbody>
</table></chapter>
"""


def test_code_blocks_and_list_items_keep_their_lines():
    row = load_script().parse_literal_sections(CODE_IN_PARA, "topic")[0]
    assert row["text"] == (
        "The clause has the general form\nGROUP BY a,\n         b < c\n"
        "and then GROUP BY condenses rows. One of\nfirst\nsecond item\napplies."
    )
    assert row["url"].endswith("queries-x.html#QUERIES-GROUP")


def test_parse_type_rows_keys_name_and_aliases():
    rows = load_script().parse_type_rows(TYPE_TABLE)
    assert [(r["key"], r["title"]) for r in rows] == [
        ("INTEGER", "integer"), ("INT", "integer"), ("INT4", "integer"), ("BOX", "box")]
    assert rows[0]["text"] == "signed four-byte integer"
    assert rows[0]["url"] == BASE + "datatype.html"


def test_section_text_stops_before_1500_characters_at_a_paragraph():
    mod = load_script()
    para = "<para>" + "word " * 100 + "end.</para>"
    body = "<sect1 id='x'><sect2 id='y'><title><literal>TOPIC</literal></title>" + para * 5 + "</sect2></sect1>"
    text = mod.parse_literal_sections(body, "topic")[0]["text"]
    assert text.endswith("end.") and len(text) < 1500
    assert text.count("end.") == 2


def test_parse_kwlist():
    assert load_script().parse_kwlist(KWLIST) == {
        "ABORT": "non-reserved",
        "SELECT": "reserved",
        "COALESCE": "non-reserved (cannot be function or type)",
        "LEFT": "reserved (can be function or type)",
    }


def test_sgml_text_drops_comments_indexterms_and_unknown_entities():
    mod = load_script()
    out = mod.sgml_text("a <!-- c --> b<indexterm><primary>z</primary></indexterm> &nbsp;c &bogus; &amp;")
    assert out == "a b c &"


def test_escaped_angle_brackets_survive_the_stripper():
    mod = load_script()
    assert mod.sgml_text("<screen>&lt;foo&gt;abc&lt;/foo&gt;</screen>") == "<foo>abc</foo>"
    assert "foo" not in mod.DOCBOOK_TAGS and "para" in mod.DOCBOOK_TAGS


def test_xref_resolves_to_title_defined_in_another_file(monkeypatch):
    mod = load_script()
    other = '<sect1 id="Other-Page"><title>The <literal>Other</literal> Page</title><para>x</para></sect1>'
    ref = '<refentry id="SQL-FOO"><refnamediv><refname>FOO</refname></refnamediv></refentry>'
    titles = mod.collect_titles(ref, mod.collect_titles(other, {}))
    monkeypatch.setattr(mod, "XREF_TITLES", titles)
    assert mod.sgml_text('(see <xref linkend="other-page"/> for details)') == "(see The Other Page for details)"
    assert mod.sgml_text('see <xref linkend="sql-foo"/>.') == "see FOO."


def test_unresolved_xref_leaves_no_dangling_see(monkeypatch):
    mod = load_script()
    monkeypatch.setattr(mod, "XREF_TITLES", {})
    monkeypatch.setattr(mod, "UNRESOLVED", [])
    assert mod.sgml_text('Truncates (see <xref linkend="nope"/>) rows; see <xref linkend="nope"/>.') == "Truncates rows."


MUST_HAVE = ["SELECT", "INSERT", "UPDATE", "DELETE", "CREATE TABLE", "WITH", "WHERE",
             "GROUP BY", "HAVING", "ORDER BY", "LIMIT", "DISTINCT", "UNION", "JOIN",
             "LEFT JOIN", "LEFT OUTER JOIN", "INNER JOIN", "OUTER JOIN", "CASE", "COALESCE", "NULLIF",
             "COUNT", "SUM", "ROW_NUMBER", "LOWER", "DATE_TRUNC", "NOW",
             "INTEGER", "NUMERIC", "TIMESTAMP"]


def test_index_has_the_everyday_words():
    missing = [k for k in MUST_HAVE if k not in INDEX["entries"]]
    assert missing == []


def test_every_entry_is_complete():
    markup = re.compile(r"</?(%s)[ >/]" % "|".join(load_script().DOCBOOK_TAGS))
    for key, entries in INDEX["entries"].items():
        assert key == key.upper() and "  " not in key
        for e in entries:
            assert e["title"] and e["text"].strip()
            for field in ("text", "title", "synopsis"):
                # no leftover DocBook markup or entities
                assert not markup.search(e.get(field, "")), (key, field)
                assert not re.search(r"&[a-z]+;", e.get(field, "")), (key, field)
            assert e["url"].startswith("https://www.postgresql.org/docs/17/")


def test_fragments_are_upper_case():
    for entries in INDEX["entries"].values():
        for e in entries:
            frag = e["url"].partition("#")[2]
            assert frag == frag.upper()


def test_integer_comes_from_the_main_type_table():
    assert "four-byte" in INDEX["entries"]["INTEGER"][0]["text"]


def test_no_empty_reference_leftovers():
    for key, entries in INDEX["entries"].items():
        for e in entries:
            assert not re.search(r"\bsee\s+for\b|\bsee\s*[.;,)]|\(see\s*\)|\(\s+\)", e["text"]), (key, e["text"][:200])


def test_reserved_words():
    assert INDEX["reserved"]["SELECT"] == "reserved"
    assert INDEX["reserved"]["ABORT"] == "non-reserved"


def test_size_budget():
    assert INDEX_PATH.stat().st_size < 2_000_000


def test_links_shape():
    for d in ("mysql", "redshift", "athena"):
        assert "{q}" in LINKS[d]["search"]
    assert len(LINKS["mysql"]["pages"]) >= 20


def test_copyright_file_is_committed():
    assert "PostgreSQL" in (INDEX_PATH.parent / "POSTGRESQL-COPYRIGHT.txt").read_text()


def test_kind_order_puts_a_type_before_a_function():
    order = load_script().KIND_ORDER
    assert order == ["command", "clause", "type", "function", "topic"]
    assert [e["kind"] for e in INDEX["entries"]["TEXT"]][:2] == ["type", "function"]


def test_phrase_entries_are_titled_by_their_source_term():
    entries = INDEX["entries"]
    assert entries["LEFT JOIN"][0]["title"] == "LEFT OUTER JOIN"
    assert entries["RIGHT JOIN"][0]["title"] == "RIGHT OUTER JOIN"
    assert entries["CROSS JOIN"][0]["title"] == "Cross join"
    assert entries["JOIN"][0]["title"] == "FROM Clause"
