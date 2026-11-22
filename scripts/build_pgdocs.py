#!/usr/bin/env python3
"""Build web/public/docs/pg17.json from the PostgreSQL 17 source tarball.

Every text, title and synopsis in the index is extracted from the PostgreSQL
documentation source; nothing is written by hand. Network access happens once,
in main(), to fetch the tarball into ~/.cache/sqldash/.
"""
import html.entities
import json
import re
import sys
import tarfile
import urllib.request
from pathlib import Path

PG_VERSION = "17.7"
TARBALL_URL = f"https://ftp.postgresql.org/pub/source/v{PG_VERSION}/postgresql-{PG_VERSION}.tar.bz2"
CACHE_DIR = Path.home() / ".cache" / "sqldash"
OUT_DIR = Path(__file__).resolve().parent.parent / "web" / "public" / "docs"
DOCS_BASE = "https://www.postgresql.org/docs/17/"
CLIENT_NAME = "sqldash-build"

TEXT_BUDGET = 1500
KEY_RE = re.compile(r"[A-Z_][A-Z0-9_]*( [A-Z_][A-Z0-9_]*)*$")
KIND_ORDER = ["command", "clause", "type", "function", "topic"]

# the docs' own entities, which the source declares outside the files we read
OWN_ENTITIES = {
    "productname": "PostgreSQL",
    "majorversion": "17",
    "version": "17",
    "zwsp": "",
    "nbsp": " ",
}

KW_LABELS = {
    "RESERVED_KEYWORD": "reserved",
    "UNRESERVED_KEYWORD": "non-reserved",
    "COL_NAME_KEYWORD": "non-reserved (cannot be function or type)",
    "TYPE_FUNC_NAME_KEYWORD": "reserved (can be function or type)",
}

# Phrases the parsers do not reach on their own, mapped to where the docs
# describe them: (source file, the varlistentry term as spelled there, paragraphs to skip).
# The text is still read from the docs.
PHRASES = {
    "JOIN": ("select.sgml", "join_type", 1),
    "INNER JOIN": ("queries.sgml", "INNER JOIN", 0),
    "LEFT JOIN": ("queries.sgml", "LEFT OUTER JOIN", 0),
    "LEFT OUTER JOIN": ("queries.sgml", "LEFT OUTER JOIN", 0),
    "RIGHT JOIN": ("queries.sgml", "RIGHT OUTER JOIN", 0),
    "RIGHT OUTER JOIN": ("queries.sgml", "RIGHT OUTER JOIN", 0),
    "FULL JOIN": ("queries.sgml", "FULL OUTER JOIN", 0),
    "FULL OUTER JOIN": ("queries.sgml", "FULL OUTER JOIN", 0),
    "CROSS JOIN": ("queries.sgml", "Cross join", 0),
    "OUTER JOIN": ("queries.sgml", "Qualified joins", 0),
}

# element names the DocBook source files use, scanned once from doc/src/sgml/**/*.sgml; the stripper removes these
DOCBOOK_TAGS = (
    'abbrev', 'abstract', 'acronym', 'address', 'anchor', 'appendix', 'application', 'arg',
    'attribution', 'author', 'authorgroup', 'bibliodiv', 'biblioentry', 'bibliography',
    'biblioset', 'blockquote', 'book', 'bookinfo', 'callout', 'calloutlist', 'caution',
    'chapter', 'citerefentry', 'citetitle', 'classname', 'cmdsynopsis', 'co', 'colspec',
    'columnname', 'command', 'computeroutput', 'confdates', 'confgroup', 'conftitle',
    'copyright', 'corpauthor', 'date', 'dbname', 'edition', 'email', 'emphasis', 'entry',
    'envar', 'example', 'figure', 'filename', 'firstname', 'firstterm', 'footnote',
    'footnoteref', 'formalpara', 'function', 'glossdef', 'glossentry', 'glosslist',
    'glosssee', 'glossseealso', 'glossterm', 'group', 'holder', 'imagedata', 'imageobject',
    'important', 'index', 'indexterm', 'informaltable', 'isbn', 'itemizedlist', 'keycap',
    'keycombo', 'legalnotice', 'lineannotation', 'link', 'listitem', 'literal',
    'literallayout', 'manvolnum', 'mediaobject', 'member', 'note', 'option', 'optional',
    'orderedlist', 'pagenums', 'para', 'parameter', 'part', 'partintro', 'phrase',
    'preface', 'primary', 'procedure', 'productname', 'productnumber', 'programlisting',
    'prompt', 'pubdate', 'publisher', 'publishername', 'pubsnumber', 'quote', 'refentry',
    'refentrytitle', 'reference', 'refmeta', 'refmiscinfo', 'refname', 'refnamediv',
    'refpurpose', 'refsect1', 'refsect2', 'refsect3', 'refsynopsisdiv', 'replaceable',
    'returnvalue', 'row', 'schemaname', 'screen', 'secondary', 'sect1', 'sect2', 'sect3',
    'sect4', 'see', 'seealso', 'sgmltag', 'simpara', 'simplelist', 'simplesect', 'spanspec',
    'step', 'structfield', 'structname', 'substeps', 'subtitle', 'superscript', 'surname',
    'symbol', 'synopsis', 'systemitem', 'table', 'tablename', 'tbody', 'term', 'tertiary',
    'tgroup', 'thead', 'tip', 'title', 'titleabbrev', 'token', 'town', 'trademark', 'type',
    'ulink', 'userinput', 'variablelist', 'varlistentry', 'varname', 'volumenum', 'warning',
    'xref', 'year',
)

# blocks cut out of a section body before its paragraphs are read (code and lists inside a paragraph stay)
DROP_BLOCKS = ["table", "informaltable", "note", "tip", "warning", "caution", "example", "figure",
               "variablelist", "simplelist", "procedure", "indexterm", "footnote"]
CODE_RE = re.compile(r"<(synopsis|programlisting|screen)\b[^>]*>.*?</\1>", re.S)
PARA_TAG = re.compile(r"<(/?)(para|itemizedlist|orderedlist|synopsis|programlisting|screen)\b[^>]*>")


# ---------------------------------------------------------------- text


def _entity(match):
    name = match.group(1)
    if name.startswith("#"):
        try:
            code = int(name[2:], 16) if name[1:2] in "xX" else int(name[1:])
            return chr(code)
        except ValueError:
            return ""
    if name in OWN_ENTITIES:
        return OWN_ENTITIES[name]
    return html.entities.html5.get(name + ";", "")  # unknown entities become nothing


# link target id (lower case) -> title, filled from every doc source file by collect_titles
XREF_TITLES = {}
XREF_RE = re.compile(r"""<xref\b[^>]*\blinkend=["']([^"']+)["'][^>]*?/?>(?:</xref>)?""")
# ids that no title was found for, waiting for the entry that used them
UNRESOLVED = []
UNRESOLVED_COUNT = 0


def _xref(match):
    global UNRESOLVED_COUNT
    title = XREF_TITLES.get(match.group(1).lower())
    if title is None:
        UNRESOLVED.append(match.group(1))
        UNRESOLVED_COUNT += 1
        return "\0"
    return title


def sgml_text(s, keep_lines=False):
    """Reduce an SGML fragment to its text."""
    s = re.sub(r"<!--.*?-->", "", s, flags=re.S)
    # a cross-reference reads as its target's title; one whose target is not in the files read leaves
    # a marker, and the "see" that pointed at it goes with it
    s = XREF_RE.sub(_xref, s)
    if "\0" in s:
        s = re.sub(r"\(\s*(?:see|See)\s*\0\s*\)", "", s)
        s = re.sub(r"[;,]?\s*\b(?:see|See)\s*\0(?=\s*[.;,)]|\s*$)", "", s)
        s = s.replace("\0", "")
    s = re.sub(r"<indexterm\b.*?</indexterm>", "", s, flags=re.S)
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"&(#?[A-Za-z0-9._-]+);", _entity, s)
    s = s.replace("\xa0", " ")
    if keep_lines:
        lines = [ln.rstrip() for ln in s.strip("\n").split("\n")]
        return "\n".join(lines).strip()
    return re.sub(r"\s+", " ", s).strip()


def strip_blocks(s, names):
    """Drop every block of the named tags, nested ones included."""
    pattern = re.compile(r"<(/?)(%s)\b[^>]*>" % "|".join(names))
    out, pos, depth = [], 0, 0
    for m in pattern.finditer(s):
        if depth == 0:
            out.append(s[pos:m.start()])
        depth += -1 if m.group(1) else 1
        depth = max(depth, 0)
        if depth == 0:
            pos = m.end()
    if depth == 0:
        out.append(s[pos:])
    return "".join(out)


def prose_text(s):
    """A paragraph's text: prose collapsed to single spaces; code blocks and list items on their own lines."""
    out, pos = [], 0

    def prose(part):
        part = re.sub(r"</?listitem\b[^>]*>", "\x01", part)
        return re.sub(r" *\x01 *", "\n", sgml_text(part))

    for m in CODE_RE.finditer(s):
        out.append(prose(s[pos:m.start()]))
        out.append(sgml_text(m.group(0), keep_lines=True))
        pos = m.end()
    out.append(prose(s[pos:]))
    return re.sub(r"\n{2,}", "\n", "\n".join(p for p in out if p)).strip()


def top_paragraphs(body):
    """Bodies of the paragraphs that are not inside a list or listing."""
    paras, stack, start = [], [], 0
    for m in PARA_TAG.finditer(body):
        tag = m.group(2)
        if m.group(1):
            if stack and stack[-1] == tag:
                stack.pop()
                if tag == "para" and not stack:
                    paras.append(body[start:m.start()])
        else:
            if tag == "para" and not stack:
                start = m.end()
            stack.append(tag)
    return paras


def leading_text(body, max_paras=None, skip_paras=0):
    """Whole paragraphs from the start of a section body, under the budget, at least one."""
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    flat = strip_blocks(body, DROP_BLOCKS)
    texts = [t for t in (prose_text(p) for p in top_paragraphs(flat)) if t][skip_paras:]
    if not texts:
        return ""
    out = texts[0]
    for t in texts[1:max_paras]:
        if len(out) + 1 + len(t) >= TEXT_BUDGET:
            break
        out += ("\n" if "\n" in out or "\n" in t else " ") + t
    return out


# ---------------------------------------------------------------- sections

SECTION_TAG = re.compile(r"<(/?)(sect[1-5]|refsect[1-3]|refentry)\b([^>]*)>")


def find_sections(sgml):
    """List every sect/refsect element: tag, id, title, body span and its enclosing sections."""
    sections, stack = [], []
    for m in SECTION_TAG.finditer(sgml):
        if m.group(1) == "":
            idm = re.search(r"""\bid=["']([^"']+)["']""", m.group(3))
            xr = re.search(r"""\bxreflabel=["']([^"']+)["']""", m.group(3))
            sec = {"tag": m.group(2), "id": idm.group(1) if idm else None,
                   "xreflabel": xr.group(1) if xr else None,
                   "open_start": m.start(), "open_end": m.end(), "end": len(sgml),
                   "first_child": None, "parents": list(stack)}
            if stack and stack[-1]["first_child"] is None:
                stack[-1]["first_child"] = m.start()
            sections.append(sec)
            stack.append(sec)
        elif stack:
            stack.pop()["end"] = m.start()
    for sec in sections:
        stop = sec["first_child"] if sec["first_child"] is not None else sec["end"]
        sec["body"] = sgml[sec["open_end"]:stop]
        tm = re.search(r"<title>(.*?)</title>", sec["body"], flags=re.S)
        sec["title_raw"] = tm.group(1) if tm else ""
        sec["title"] = sgml_text(sec["title_raw"])
    return sections


def page_of(sec):
    """The id of the page a section lives on: its sect1 (or refentry), else itself."""
    for s in sec["parents"] + [sec]:
        if s["tag"] in ("sect1", "refentry") and s["id"]:
            return s["id"]
    return None


def first_synopsis(body):
    m = re.search(r"<synopsis\b[^>]*>(.*?)</synopsis>", body, flags=re.S)
    return sgml_text(m.group(1), keep_lines=True) if m else ""


def make_entry(kind, key, title, text, url, synopsis=""):
    for xref_id in UNRESOLVED:
        print(f"unresolved xref {xref_id} in {key}", file=sys.stderr)
    UNRESOLVED.clear()
    entry = {"key": key, "kind": kind, "title": title, "text": text, "url": url}
    if synopsis:
        entry["synopsis"] = synopsis
    return entry


# ---------------------------------------------------------------- parsers


def parse_ref_page(sgml):
    """Entries for one reference page: the command and each clause section."""
    rm = re.search(r"""<refentry\b[^>]*\bid=["']([^"']+)["']""", sgml)
    if not rm:
        return []
    misc = re.search(r"<refmiscinfo>(.*?)</refmiscinfo>", sgml, flags=re.S)
    if misc and not sgml_text(misc.group(1)).startswith("SQL"):
        return []  # application pages (psql, pg_dump) are not SQL
    page = DOCS_BASE + rm.group(1).lower() + ".html"
    rows = []
    sections = find_sections(sgml)

    purpose = re.search(r"<refpurpose>(.*?)</refpurpose>", sgml, flags=re.S)
    purpose = sgml_text(purpose.group(1)) if purpose else ""
    lead = ""
    for sec in sections:
        if sec["tag"] == "refsect1" and sec["title"] == "Description":
            lead = leading_text(sec["body"], max_paras=1)
            break
    text = ". ".join(p for p in (purpose, lead) if p)
    syn = re.search(r"<refsynopsisdiv>(.*?)</refsynopsisdiv>", sgml, flags=re.S)
    synopsis = "\n\n".join(
        sgml_text(b, keep_lines=True)
        for b in re.findall(r"<synopsis\b[^>]*>(.*?)</synopsis>", syn.group(1) if syn else "", flags=re.S))
    for name in re.findall(r"<refname>(.*?)</refname>", sgml, flags=re.S):
        name = sgml_text(name)
        key = name.upper()
        if text and KEY_RE.match(key):
            rows.append(make_entry("command", key, name, text, page, synopsis))

    for sec in sections:
        if sec["tag"] != "refsect2" or not sec["id"]:
            continue
        label = sgml_text(sec["xreflabel"]) if sec["xreflabel"] else sec["title"]
        m = re.match(r"(?:The\s+)?(.+?)\s+Clauses?$", label)
        if not m:
            continue
        key = m.group(1).upper()
        body_text = leading_text(sec["body"])
        if KEY_RE.match(key) and body_text:
            rows.append(make_entry("clause", key, label, body_text, page + "#" + sec["id"].upper()))
    return rows


def parse_func_rows(sgml):
    """One entry per function signature in the func_table_entry rows."""
    sections = find_sections(sgml)
    sect1s = [s for s in sections if s["tag"] == "sect1"]
    rows, seen = [], set()
    for em in re.finditer(r"""<entry\b[^>]*role=["']func_table_entry["'][^>]*>(.*?)</entry>""", sgml, flags=re.S):
        enclosing = [s for s in sect1s if s["open_start"] < em.start() < s["end"]]
        if not enclosing or not enclosing[-1]["id"]:
            continue
        url = DOCS_BASE + enclosing[-1]["id"].lower() + ".html"
        paras = re.findall(r"<para\b([^>]*)>(.*?)</para>", em.group(1), flags=re.S)
        sigs = [body for attrs, body in paras if "func_signature" in attrs]
        plain = [body for attrs, body in paras if "func_signature" not in attrs]
        desc = sgml_text(plain[0]) if plain else ""
        if not desc:
            continue
        for sig in sigs:
            fm = re.search(r"<function>(.*?)</function>", sig, flags=re.S)
            if not fm:
                continue  # operator rows have no function name
            name = sgml_text(fm.group(1))
            key = name.upper()
            if not KEY_RE.match(key):
                continue
            synopsis = sgml_text(sig)
            if (key, synopsis, desc) in seen:
                continue
            seen.add((key, synopsis, desc))
            rows.append(make_entry("function", key, name, desc, url, synopsis))
    return rows


def parse_literal_sections(sgml, kind):
    """Entries for sections whose title opens with a literal word, such as COALESCE."""
    rows = []
    for sec in find_sections(sgml):
        if not sec["id"] or not re.match(r"\s*(?:The\s+)?<literal>", sec["title_raw"]):
            continue
        keys = [sgml_text(k).upper() for k in re.findall(r"<literal>(.*?)</literal>", sec["title_raw"], flags=re.S)]
        keys = [k for k in keys if KEY_RE.match(k)]
        text = leading_text(sec["body"])
        page = page_of(sec)
        if not keys or not text or not page:
            continue
        url = DOCS_BASE + page.lower() + ".html"
        if kind == "topic" and sec["id"] != page:
            url += "#" + sec["id"].upper()
        for key in keys:
            rows.append(make_entry(kind, key, sec["title"], text, url, first_synopsis(sec["body"])))
    return rows


def parse_type_rows(sgml):
    """Entries for the rows of the main data type table (Name, Aliases, Description)."""
    tm = re.search(r"""<table\b[^>]*\bid=["']datatype-table["'][^>]*>.*?</table>""", sgml, flags=re.S)
    cm = re.search(r"""<chapter\b[^>]*\bid=["']([^"']+)["']""", sgml)
    if not tm or not cm:
        return []
    url = DOCS_BASE + cm.group(1).lower() + ".html"
    rows = []
    for rm in re.finditer(r"<row>(.*?)</row>", tm.group(0).split("</thead>", 1)[-1], flags=re.S):
        cells = re.findall(r"<entry\b[^>]*>(.*?)</entry>", rm.group(1), flags=re.S)
        if len(cells) < 3:
            continue
        name, aliases, desc = (sgml_text(c) for c in cells[:3])
        keys = []
        for label in [name] + aliases.split(","):
            word = re.match(r"""[\s"]*([A-Za-z_][A-Za-z0-9_]*)""", label)
            key = word.group(1).upper() if word else ""
            if KEY_RE.match(key) and key not in keys:
                keys.append(key)
        if desc:
            rows += [make_entry("type", key, name, desc, url) for key in keys]
    return rows


def parse_terms(sgml, wanted, skip_paras=0):
    """Text of the varlistentry whose term reads as one of the wanted terms."""
    sections = find_sections(sgml)
    found = {}
    for m in re.finditer(r"<varlistentry\b[^>]*>", sgml):
        # find the matching close, counting nested entries
        depth, end = 0, None
        for t in re.finditer(r"<(/?)varlistentry\b", sgml[m.start():]):
            depth += -1 if t.group(1) else 1
            if depth == 0:
                end = m.start() + t.end()
                break
        block = sgml[m.start():end] if end else ""
        tm = re.search(r"<term>(.*?)</term>", block, flags=re.S)
        if not tm:
            continue
        term = sgml_text(tm.group(1))
        if term not in wanted or term in found:
            continue
        li = re.search(r"<listitem>(.*)</listitem>", block[tm.end():], flags=re.S)
        text = leading_text(li.group(1), skip_paras=skip_paras) if li else ""
        enclosing = [s for s in sections if s["open_start"] < m.start() < s["end"]]
        found[term] = (text, enclosing)
    return found


def parse_kwlist(text):
    """Keyword label per word from kwlist.h."""
    out = {}
    for word, cat in re.findall(r'PG_KEYWORD\("([a-z0-9_]+)",\s*\w+,\s*(\w+)', text):
        if cat in KW_LABELS:
            out[word.upper()] = KW_LABELS[cat]
    return out


# ---------------------------------------------------------------- build


TITLED_ID = re.compile(
    r"""<([a-z0-9]+)\b[^>]*\bid=["']([^"']+)["'][^>]*>\s*(?:<indexterm\b.*?</indexterm>\s*)*<title>(.*?)</title>""", re.S)
TERM_ID = re.compile(
    r"""<varlistentry\b[^>]*\bid=["']([^"']+)["'][^>]*>\s*<term>(.*?)</term>""", re.S)


def collect_titles(sgml, titles):
    """Add id -> title for every element in one source file that carries an id and a title."""
    for m in TITLED_ID.finditer(sgml):
        titles[m.group(2).lower()] = sgml_text(m.group(3))
    for m in TERM_ID.finditer(sgml):
        titles.setdefault(m.group(1).lower(), sgml_text(m.group(2)))
    rm = re.search(r"""<refentry\b[^>]*\bid=["']([^"']+)["']""", sgml)
    nm = re.search(r"<refname>(.*?)</refname>", sgml, flags=re.S)
    if rm and nm:
        titles[rm.group(1).lower()] = sgml_text(nm.group(1))
    return titles


def phrase_entries(files):
    """Entries for PHRASES, with text read from the named source files."""
    rows = []
    for phrase, (fname, term, skip) in PHRASES.items():
        sgml = files[fname]
        text, enclosing = parse_terms(sgml, {term}, skip)[term]
        ids = [s for s in enclosing if s["id"]]
        page = next((s["id"] for s in ids if s["tag"] in ("sect1", "refentry")), None)
        if not text or not page:
            raise SystemExit(f"phrase {phrase!r}: nothing found for term {term!r} in {fname}")
        url = DOCS_BASE + page.lower() + ".html"
        inner = ids[-1]["id"]
        if inner != page:
            url += "#" + inner.upper()
        # the source's own term titles the entry; a placeholder term (join_type) falls back to its section's title
        title = ids[-1]["title"] if "_" in term else term
        rows.append(make_entry("clause", phrase, title, text, url))
    return rows


def read_members(tar_path):
    """Read the needed source files straight from the tar stream."""
    root = f"postgresql-{PG_VERSION}/"
    wanted = {root + "doc/src/sgml/func.sgml": "func.sgml",
              root + "doc/src/sgml/datatype.sgml": "datatype.sgml",
              root + "doc/src/sgml/queries.sgml": "queries.sgml",
              root + "doc/src/sgml/ref/select.sgml": "select.sgml",
              root + "src/include/parser/kwlist.h": "kwlist.h",
              root + "COPYRIGHT": "COPYRIGHT"}
    files, refs, titles = {}, {}, {}
    with tarfile.open(tar_path, "r:bz2") as tar:
        for m in tar:
            if not m.isfile():
                continue
            is_sgml = m.name.startswith(root + "doc/src/sgml/") and m.name.endswith(".sgml")
            if m.name not in wanted and not is_sgml:
                continue
            text = tar.extractfile(m).read().decode("utf-8")
            if m.name in wanted:
                files[wanted[m.name]] = text
            if m.name.startswith(root + "doc/src/sgml/ref/") and is_sgml:
                refs[m.name] = text
            if is_sgml:
                collect_titles(text, titles)  # every doc file, for cross-references
    return files, refs, titles


def build_index(files, refs, titles):
    XREF_TITLES.update(titles)
    UNRESOLVED.clear()  # xrefs met while reading titles do not belong to any entry
    global UNRESOLVED_COUNT
    UNRESOLVED_COUNT = 0
    rows = []
    for name in sorted(refs):
        rows += parse_ref_page(refs[name])
    rows += parse_literal_sections(files["queries.sgml"], "topic")
    rows += parse_literal_sections(files["func.sgml"], "function")
    rows += parse_func_rows(files["func.sgml"])
    rows += parse_type_rows(files["datatype.sgml"])
    rows += phrase_entries(files)
    entries = {}
    for row in sorted(rows, key=lambda r: KIND_ORDER.index(r["kind"])):
        key = row.pop("key")
        if row not in entries.setdefault(key, []):
            entries[key].append(row)
    return {"pg_version": PG_VERSION,
            "entries": dict(sorted(entries.items())),
            "reserved": dict(sorted(parse_kwlist(files["kwlist.h"]).items()))}


def fetch_tarball():
    path = CACHE_DIR / f"postgresql-{PG_VERSION}.tar.bz2"
    if not path.exists():
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(TARBALL_URL, headers={"User-Agent": CLIENT_NAME})
        tmp = path.with_suffix(".part")
        with urllib.request.urlopen(req, timeout=120) as resp, open(tmp, "wb") as out:
            while chunk := resp.read(1 << 20):
                out.write(chunk)
        tmp.rename(path)
    return path


def main():
    files, refs, titles = read_members(fetch_tarball())
    index = build_index(files, refs, titles)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "pg17.json"
    out.write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    (OUT_DIR / "POSTGRESQL-COPYRIGHT.txt").write_text(files["COPYRIGHT"], encoding="utf-8")
    print(f"keys: {len(index['entries'])}  reserved: {len(index['reserved'])}  bytes: {out.stat().st_size}  unresolved xrefs: {UNRESOLVED_COUNT}")


if __name__ == "__main__":
    main()
