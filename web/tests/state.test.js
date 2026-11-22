import test from "node:test";
import assert from "node:assert/strict";
import {
  initial, editSql, editEnglish, setDialect, checkStarted, checkDone,
  applySummary, setVerdict, needsConfirm, summaryOutdated,
  applySql, applyNames, editName, swap, needsSqlConfirm, sqlOutdated, namesPending,
} from "../src/lib/state.js";
import { nameKey } from "../src/lib/names.js";

test("initial defaults and saved values", () => {
  assert.deepEqual(initial(), {
    sql: "", english: "", dialect: "postgres", origin: "yours", check: null, summaryMeta: null, verdict: null,
    direction: "sql_to_english", sqlOrigin: "yours", sqlMeta: null, base: "", names: null, namesFailed: false, edits: {}, note: "",
  });
  const s = initial({ sql: "select 1", english: "one", dialect: "mysql", origin: "ai" });
  assert.deepEqual([s.sql, s.english, s.dialect, s.origin], ["select 1", "one", "mysql", "ai"]);
  const bad = initial({ sql: 3, english: null, dialect: "oracle", origin: "robot" });
  assert.deepEqual([bad.sql, bad.english, bad.dialect, bad.origin], ["", "", "postgres", "yours"]);
  assert.equal(initial("junk").dialect, "postgres");
  assert.equal(initial(null).sql, "");
});

test("summary, verdict, edits", () => {
  let s = applySummary(initial(), { text: "It reads t.", model: "m", input_tokens: 1, output_tokens: 2 });
  assert.equal(s.origin, "ai");
  assert.equal(s.english, "It reads t.");
  assert.deepEqual(s.summaryMeta, { model: "m", input_tokens: 1, output_tokens: 2, stale: false });
  assert.equal(needsConfirm(s), false);
  s = setVerdict(s, { choice: "agrees", confidence: 0.9 });
  assert.deepEqual(s.verdict, { choice: "agrees", confidence: 0.9 });
  s = editSql(s, "select 2");
  assert.equal(s.verdict, null);
  assert.equal(s.summaryMeta.stale, true);
  s = editEnglish(s, "my own words");
  assert.equal(s.origin, "yours");
  assert.equal(s.summaryMeta, null);
  assert.equal(needsConfirm(s), true);
  assert.equal(needsConfirm(editEnglish(s, "   ")), false);
});

test("applySummary clears a verdict", () => {
  const s = setVerdict(initial(), { choice: "agrees", confidence: 1 });
  assert.equal(applySummary(s, { text: "x", model: "m", input_tokens: 0, output_tokens: 0 }).verdict, null);
});

test("check goes stale on edits, dialect change and a new check", () => {
  assert.equal(checkStarted(checkDone(initial(), { ok: true })).check.stale, true);
  assert.equal(checkDone(initial(), { ok: true }).check.stale, false);
  assert.equal(checkStarted(initial()).check, null);
  const c = checkDone(initial(), { ok: false, message: "m" });
  assert.equal(c.check.message, "m");
  assert.equal(editSql(c, "select 1").check.stale, true);
  assert.equal(setDialect(c, "mysql").check.stale, true);
  assert.equal(editSql(initial(), "select 1").check, null);
});

test("setDialect clears verdict and marks summaryMeta stale", () => {
  assert.equal(setDialect(setVerdict(initial(), { choice: "agrees", confidence: 1 }), "mysql").verdict, null);
  const s = applySummary(initial(), { text: "x", model: "m", input_tokens: 0, output_tokens: 0 });
  const d = setDialect(s, "athena");
  assert.equal(d.dialect, "athena");
  assert.equal(d.summaryMeta.stale, true);
});

test("unchanged edits return the same state", () => {
  const s = editEnglish(editSql(initial(), "select 1"), "x");
  assert.equal(editSql(s, "select 1"), s);
  assert.equal(editEnglish(s, "x"), s);
});

test("functions never mutate their input", () => {
  const frozen = (o) => Object.freeze(o);
  const meta = frozen({ model: "m", input_tokens: 1, output_tokens: 2, stale: false });
  const s = frozen({
    sql: "a", english: "b", dialect: "postgres", origin: "ai",
    check: frozen({ ok: true, stale: false }), summaryMeta: meta, verdict: frozen({ choice: "agrees", confidence: 1 }),
  });
  const r = frozen({ text: "t", model: "m", input_tokens: 1, output_tokens: 2 });
  const outs = [
    editSql(s, "c"), editEnglish(s, "d"), setDialect(s, "mysql"), checkStarted(s),
    checkDone(s, { ok: false }), applySummary(s, r), setVerdict(s, { choice: "x", confidence: 0 }),
  ];
  for (const o of outs) assert.notEqual(o, s);
  assert.equal(s.sql, "a");
  assert.equal(s.check.stale, false);
  assert.equal(s.summaryMeta.stale, false);
});

test("summaryOutdated marks an existing summaryMeta stale", () => {
  assert.equal(summaryOutdated(initial()).summaryMeta, null);
  const s = applySummary(initial(), { text: "x", model: "m", input_tokens: 1, output_tokens: 2 });
  const o = summaryOutdated(s);
  assert.equal(o.summaryMeta.stale, true);
  assert.equal(s.summaryMeta.stale, false);
});

const R = { sql: "SELECT name, salary\nFROM employees\nWHERE salary > 100", note: "", model: "m", input_tokens: 3, output_tokens: 4 };
const N = { ok: true, names: [
  { kind: "column", name: "name", table: "employees", spans: [[7, 11]] },
  { kind: "column", name: "salary", table: "employees", spans: [[13, 19], [41, 47]] },
  { kind: "table", name: "employees", table: null, spans: [[25, 34]] },
] };
const SALARY = nameKey(N.names[1]);
const toSql = () => swap(editEnglish(initial(), "people paid over 100"));

test("a state saved by the old page loads as SQL to English", () => {
  const s = initial({ sql: "select 1", english: "one", dialect: "mysql", origin: "ai" });
  assert.equal(s.direction, "sql_to_english");
  assert.deepEqual([s.base, s.edits, s.note, s.sqlOrigin, s.names, s.namesFailed, s.sqlMeta], ["", {}, "", "yours", null, false, null]);
});

test("initial reads the new fields and rejects bad ones", () => {
  const s = initial({ sql: "SELECT pay", english: "e", direction: "english_to_sql", sqlOrigin: "ai", base: "SELECT salary", edits: { k: "pay" }, note: "n" });
  assert.deepEqual([s.direction, s.sqlOrigin, s.base, s.edits, s.note, s.sql], ["english_to_sql", "ai", "SELECT salary", { k: "pay" }, "n", "SELECT pay"]);
  const bad = initial({ sql: "x", direction: "sideways", sqlOrigin: "robot", base: 3, edits: { k: 1 }, note: null });
  assert.deepEqual([bad.direction, bad.sqlOrigin, bad.base, bad.edits, bad.note], ["sql_to_english", "yours", "", {}, ""]);
  assert.deepEqual(initial({ edits: [1] }).edits, {});
  const noBase = initial({ sql: "select 1", direction: "english_to_sql" });
  assert.equal(noBase.base, "select 1");
  const leftover = initial({ sql: "select 1", direction: "sql_to_english", base: "old", edits: { k: "v" } });
  assert.deepEqual([leftover.base, leftover.edits], ["", {}]);
});

test("applySql fills the right-hand SQL with its names", () => {
  const s = applySql(toSql(), R, N);
  assert.deepEqual([s.sql, s.base, s.sqlOrigin, s.note, s.namesFailed], [R.sql, R.sql, "ai", "", false]);
  assert.deepEqual(s.names, N.names);
  assert.deepEqual(s.sqlMeta, { model: "m", input_tokens: 3, output_tokens: 4, stale: false });
  assert.equal(s.english, "people paid over 100");
  assert.equal(s.origin, "yours");
});

test("editName changes every occurrence, from the original text each time", () => {
  let s = applySql(toSql(), R, N);
  s = setVerdict(checkDone(s, { ok: true, exact: true, error: null }), { choice: "agrees", confidence: 0.9 });
  s = editName(s, SALARY, "pa");
  s = editName(s, SALARY, "pay");
  assert.equal(s.sql, "SELECT name, pay\nFROM employees\nWHERE pay > 100");
  assert.equal(s.base, R.sql);
  assert.equal(s.verdict, null);
  assert.equal(s.check.stale, true);
  assert.equal(s.sqlOrigin, "ai");
  assert.equal(s.sqlMeta.stale, false);
  s = editName(s, SALARY, "");
  assert.equal(s.sql, R.sql);
  assert.equal(s.edits[SALARY], "");
  s = editName(s, SALARY, null);
  assert.equal(SALARY in s.edits, false);
});

test("a new result re-applies an edit when the name appears again", () => {
  let s = editName(applySql(toSql(), R, N), SALARY, "pay");
  const r2 = { ...R, sql: "SELECT salary FROM employees" };
  const n2 = { ok: true, names: [
    { kind: "column", name: "salary", table: "employees", spans: [[7, 13]] },
    { kind: "table", name: "employees", table: null, spans: [[19, 28]] },
  ] };
  s = applySql(s, r2, n2);
  assert.equal(s.sql, "SELECT pay FROM employees");
  assert.equal(s.base, "SELECT salary FROM employees");
  // the same column name under another table is another name, so the edit is not carried
  const r3 = { ...R, sql: "SELECT salary FROM staff" };
  const n3 = { ok: true, names: [
    { kind: "column", name: "salary", table: "staff", spans: [[7, 13]] },
    { kind: "table", name: "staff", table: null, spans: [[19, 24]] },
  ] };
  const other = applySql(s, r3, n3);
  assert.deepEqual([other.sql, other.edits], ["SELECT salary FROM staff", {}]);
});

test("an empty result clears the box, the names and the check, and keeps the note", () => {
  let s = editName(checkDone(applySql(toSql(), R, N), { ok: true, exact: true, error: null }), SALARY, "pay");
  s = applySql(s, { ...R, sql: "", note: "Say which table." }, null);
  assert.deepEqual([s.sql, s.base, s.names, s.namesFailed, s.check, s.note], ["", "", null, false, null, "Say which table."]);
  assert.equal(s.edits[SALARY], "pay");
});

test("names that could not be read show the original SQL", () => {
  let s = applySql(toSql(), R, null);
  assert.deepEqual([s.sql, s.names, s.namesFailed], [R.sql, null, true]);
  s = applyNames(editName(applySql(toSql(), R, N), SALARY, "pay"), { ok: false, names: [] });
  assert.deepEqual([s.sql, s.names, s.namesFailed, s.edits[SALARY]], [R.sql, null, true, "pay"]);
  s = applyNames(s, N);
  assert.deepEqual([s.sql, s.namesFailed], ["SELECT name, pay\nFROM employees\nWHERE pay > 100", false]);
});

test("swap carries both texts and clears what belonged to the old direction", () => {
  let s = editName(applySql(toSql(), R, N), SALARY, "pay");
  s = setVerdict(editEnglish(s, "people paid over 200"), { choice: "differs", confidence: 0.8 });
  assert.equal(s.sqlMeta.stale, true);
  const left = swap(s);
  assert.equal(left.direction, "sql_to_english");
  assert.equal(left.sql, "SELECT name, pay\nFROM employees\nWHERE pay > 100");
  assert.equal(left.english, "people paid over 200");
  assert.deepEqual([left.base, left.names, left.edits, left.note, left.verdict], ["", null, {}, "", null]);
  assert.equal(left.sqlMeta.stale, false);
  assert.equal(left.sqlMeta.model, "m");
  assert.deepEqual([left.sqlOrigin, left.origin], ["ai", "yours"]);
  const back = swap(left);
  assert.deepEqual([back.direction, back.sql, back.base, back.english], ["english_to_sql", left.sql, left.sql, left.english]);
  assert.equal(namesPending(back), true);
});

test("who wrote the SQL", () => {
  let s = swap(applySql(toSql(), R, N));
  assert.equal(needsSqlConfirm(s), false);
  s = editSql(s, "select 2");
  assert.deepEqual([s.sqlOrigin, s.sqlMeta], ["yours", null]);
  assert.equal(needsSqlConfirm(swap(s)), true);
  assert.equal(needsSqlConfirm(swap(editSql(s, "  "))), false);
});

test("sqlOutdated, setDialect and namesPending", () => {
  const s = applySql(toSql(), R, N);
  assert.equal(sqlOutdated(s).sqlMeta.stale, true);
  assert.equal(setDialect(s, "mysql").sqlMeta.stale, true);
  assert.equal(sqlOutdated(initial()).sqlMeta, null);
  assert.equal(namesPending(s), false);
  assert.equal(namesPending(initial()), false);
  assert.equal(namesPending(initial({ sql: "select 1", direction: "english_to_sql" })), true);
  assert.equal(namesPending(applySql(toSql(), R, null)), false);
});
