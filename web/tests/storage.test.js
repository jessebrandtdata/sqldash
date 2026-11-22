import test from "node:test";
import assert from "node:assert/strict";
import { load, save } from "../src/lib/storage.js";
import { initial, editSql } from "../src/lib/state.js";

function fake() {
  const m = new Map();
  return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, v), m };
}

test("save then load round-trips the four saved fields under sqldash.v1", () => {
  const st = fake();
  save(st, editSql(initial(), "select 1"));
  assert.deepEqual([...st.m.keys()], ["sqldash.v1"]);
  assert.deepEqual(JSON.parse(st.m.get("sqldash.v1")), { sql: "select 1", english: "", dialect: "postgres", origin: "yours" });
  assert.deepEqual(load(st), { sql: "select 1", english: "", dialect: "postgres", origin: "yours" });
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
