import test from "node:test";
import assert from "node:assert/strict";
import { lineColToOffset, candidates } from "../src/lib/position.js";

test("lineColToOffset counts CRLF as one break and clamps", () => {
  assert.equal(lineColToOffset("select 1;\r\nselec 2", 2, 1), 11);
  assert.equal(lineColToOffset("a\nbc", 1, 1), 0);
  assert.equal(lineColToOffset("a\nbc", 2, 2), 3);
  assert.equal(lineColToOffset("a\nbc", 9, 9), 4);
  assert.equal(lineColToOffset("a\nbc", 1, 99), 1);
  assert.equal(lineColToOffset("", 1, 1), 0);
});

test("candidates: windows longest first, cursor word first within a length", () => {
  assert.deepEqual(candidates("select a from t left outer join u", 17), [
    "LEFT OUTER JOIN", "T LEFT OUTER", "FROM T LEFT", "LEFT OUTER", "T LEFT", "LEFT",
  ]);
});

test("candidates: cursor at the end of a word counts", () => {
  assert.deepEqual(candidates("select 1", 6), ["SELECT"]);
  assert.deepEqual(candidates("select 1", 0), ["SELECT"]);
});

test("candidates: windows cross only spaces, tabs and newlines", () => {
  assert.deepEqual(candidates("group\n\tby x", 1), ["GROUP BY X", "GROUP BY", "GROUP"]);
  assert.deepEqual(candidates("a.b c", 0), ["A"]);
  assert.deepEqual(candidates("a, b", 0), ["A"]);
});

test("candidates: not in a word", () => {
  assert.deepEqual(candidates("select  1", 7), []);
  assert.deepEqual(candidates("select 12", 8), []);
  assert.deepEqual(candidates("", 0), []);
});

test("candidates: quoted strings", () => {
  assert.deepEqual(candidates("select 'group by' from t", 10), []);
  assert.deepEqual(candidates("select 'it''s group' from t", 16), []);
  assert.deepEqual(candidates("select 'unterminated group", 20), []);
  assert.deepEqual(candidates("select 'a' from t", 14), ["FROM T", "FROM"]);
});

test("candidates: double-quoted identifiers", () => {
  assert.deepEqual(candidates('select "group by" from t', 10), []);
});

test("candidates: line and block comments", () => {
  assert.deepEqual(candidates("select 1 -- group by\n", 14), []);
  assert.deepEqual(candidates("select 1 -- group by\nfrom t", 22), ["FROM T", "FROM"]);
  assert.deepEqual(candidates("select /* group by */ 1", 13), []);
  assert.deepEqual(candidates("select /* group by", 13), []);
  assert.deepEqual(candidates("select /* x */ a", 15), ["A"]);
});

test("candidates: windows do not reach across a comment or string", () => {
  assert.deepEqual(candidates("select /* c */ a", 15), ["A"]);
  assert.deepEqual(candidates("a 'x' b", 0), ["A"]);
});
