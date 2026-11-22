import test from "node:test";
import assert from "node:assert/strict";
import { load, save } from "../src/lib/storage.js";
import { initial, editSql, applySql, editName, swap } from "../src/lib/state.js";

function fake() {
  const m = new Map();
  return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, v), m };
}

test("save then load round-trips the nine saved fields under sqldash.v1", () => {
  const st = fake();
  save(st, editSql(initial(), "select 1"));
  assert.deepEqual([...st.m.keys()], ["sqldash.v1"]);
  const want = {
    sql: "select 1", english: "", dialect: "postgres", origin: "yours",
    direction: "sql_to_english", sqlOrigin: "yours", base: "", edits: {}, note: "",
  };
  assert.deepEqual(JSON.parse(st.m.get("sqldash.v1")), want);
  assert.deepEqual(load(st), want);
});

test("name edits survive a save and load, and derived fields are not saved", () => {
  const st = fake();
  const names = [{ kind: "column", name: "salary", table: "t", spans: [[7, 13]] }];
  const key = JSON.stringify(["column", "t", "salary"]);
  let s = swap(initial());
  s = applySql(s, { sql: "SELECT salary FROM t", note: "n", model: "m", input_tokens: 1, output_tokens: 2 }, { ok: true, names });
  s = editName(s, key, "pay");
  save(st, s);
  const saved = JSON.parse(st.m.get("sqldash.v1"));
  for (const k of ["names", "check", "verdict", "sqlMeta", "summaryMeta"]) assert.equal(k in saved, false);
  const back = initial(load(st));
  assert.deepEqual([back.direction, back.sqlOrigin, back.base, back.edits, back.note, back.sql],
    ["english_to_sql", "ai", "SELECT salary FROM t", { [key]: "pay" }, "n", "SELECT pay FROM t"]);
});

test("load returns null for missing, bad, non-object and throwing stores", () => {
  assert.equal(load(fake()), null);
  assert.equal(load({ getItem: () => "{not json" }), null);
  assert.equal(load({ getItem: () => "3" }), null);
  assert.equal(load({ getItem: () => "null" }), null);
  assert.equal(load({ getItem: () => "[1]" }), null);
  assert.equal(load({ getItem() { throw new Error("blocked"); } }), null);
  assert.equal(load(null), null);
});

test("save swallows every error", () => {
  assert.doesNotThrow(() => save({ setItem() { throw new Error("blocked"); } }, initial()));
  assert.doesNotThrow(() => save(null, initial()));
});
