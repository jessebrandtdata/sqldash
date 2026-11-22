import test from "node:test";
import assert from "node:assert/strict";
import {
  initial, editSql, editEnglish, setDialect, checkStarted, checkDone,
  applySummary, setVerdict, needsConfirm,
} from "../src/lib/state.js";

test("initial defaults and saved values", () => {
  assert.deepEqual(initial(), {
    sql: "", english: "", dialect: "postgres", origin: "yours", check: null, summaryMeta: null, verdict: null,
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
