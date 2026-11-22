import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { lookup } from "../src/lib/docs.js";
import { candidates } from "../src/lib/position.js";

const PG = {
  pg_version: 17,
  entries: { "GROUP BY": [{ title: "g" }], "LEFT OUTER JOIN": [{ title: "j" }], SELECT: [{ title: "s" }], DATE_TRUNC: [{ title: "d" }] },
  reserved: { ABORT: "non-reserved", SELECT: "reserved" },
};
const LINKS = {
  mysql: { pages: { SELECT: "https://m.example/select" }, search: "https://m.example/?q={q}" },
  athena: { pages: {}, search: "https://a.example/?q={q}" },
};

test("postgres: first candidate that is an entry key", () => {
  const r = lookup("postgres", ["GROUP BY", "GROUP"], PG, LINKS);
  assert.equal(r.kind, "entries");
  assert.equal(r.key, "GROUP BY");
  assert.deepEqual(r.entries, PG.entries["GROUP BY"]);
  assert.equal(
    lookup("postgres", ["LEFT OUTER JOIN", "T LEFT OUTER", "FROM T LEFT", "LEFT OUTER", "T LEFT", "LEFT"], PG, LINKS).key,
    "LEFT OUTER JOIN",
  );
});

test("postgres: reserved-only keys give empty entries", () => {
  const r = lookup("postgres", ["X", "ABORT"], PG, LINKS);
  assert.deepEqual(r, { kind: "entries", key: "ABORT", entries: [], reserved: "non-reserved" });
});

test("postgres: entry key wins over an earlier reserved-only candidate", () => {
  assert.equal(lookup("postgres", ["ABORT", "SELECT"], PG, LINKS).key, "SELECT");
});

test("postgres: unknown identifier is null", () => {
  assert.equal(lookup("postgres", ["MY_COLUMN"], PG, LINKS), null);
  assert.equal(lookup("postgres", [], PG, LINKS), null);
});

test("other dialects: page link, then encoded search, else null", () => {
  assert.equal(lookup("mysql", ["SELECT"], PG, LINKS).url, LINKS.mysql.pages.SELECT);
  assert.equal(lookup("mysql", ["SELECT"], PG, LINKS).kind, "link");
  const a = lookup("athena", ["DATE_TRUNC"], PG, LINKS);
  assert.match(a.url, /DATE_TRUNC/);
  assert.equal(a.key, "DATE_TRUNC");
  assert.equal(lookup("athena", ["GROUP BY"], PG, LINKS).url, "https://a.example/?q=GROUP%20BY");
  assert.equal(lookup("mysql", ["MY_COLUMN"], PG, LINKS), null);
});

test("real data files", () => {
  const dir = new URL("../public/docs/", import.meta.url);
  const pg = JSON.parse(readFileSync(new URL("pg17.json", dir), "utf8"));
  const links = JSON.parse(readFileSync(new URL("links.json", dir), "utf8"));
  assert.equal(lookup("postgres", candidates("select a from t left outer join u", 17), pg, links).key, "LEFT OUTER JOIN");
  assert.equal(lookup("postgres", candidates("select coalesce(a, b)", 9), pg, links).key, "COALESCE");
});
