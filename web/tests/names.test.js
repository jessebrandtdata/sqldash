import test from "node:test";
import assert from "node:assert/strict";
import { nameKey, applyEdits, carryEdits, groupNames } from "../src/lib/names.js";

const BASE = "SELECT name, salary\nFROM employees\nWHERE salary > 100";
const NAME = { kind: "column", name: "name", table: "employees", spans: [[7, 11]] };
const SALARY = { kind: "column", name: "salary", table: "employees", spans: [[13, 19], [41, 47]] };
const EMPLOYEES = { kind: "table", name: "employees", table: null, spans: [[25, 34]] };
const NAMES = [NAME, SALARY, EMPLOYEES];

test("nameKey tells kind, table and name apart", () => {
  assert.equal(nameKey(SALARY), '["column","employees","salary"]');
  assert.notEqual(nameKey({ ...SALARY, table: null }), nameKey(SALARY));
  assert.notEqual(nameKey({ ...EMPLOYEES, kind: "column" }), nameKey(EMPLOYEES));
});

test("an edit replaces every occurrence", () => {
  const out = applyEdits(BASE, NAMES, { [nameKey(SALARY)]: "pay" });
  assert.equal(out, "SELECT name, pay\nFROM employees\nWHERE pay > 100");
});

test("several edits of different lengths at once", () => {
  const edits = { [nameKey(SALARY)]: "annual_salary", [nameKey(EMPLOYEES)]: "hr.staff", [nameKey(NAME)]: "n" };
  assert.equal(applyEdits(BASE, NAMES, edits), "SELECT n, annual_salary\nFROM hr.staff\nWHERE annual_salary > 100");
});

test("no edits, blank edits and missing names leave the text alone", () => {
  assert.equal(applyEdits(BASE, NAMES, {}), BASE);
  assert.equal(applyEdits(BASE, NAMES, { [nameKey(SALARY)]: "" }), BASE);
  assert.equal(applyEdits(BASE, NAMES, { [nameKey(SALARY)]: "  " }), BASE);
  assert.equal(applyEdits(BASE, NAMES, { [nameKey(SALARY)]: 7 }), BASE);
  assert.equal(applyEdits(BASE, null, { [nameKey(SALARY)]: "pay" }), BASE);
  assert.equal(applyEdits(BASE, [], { [nameKey(SALARY)]: "pay" }), BASE);
});

test("an edit is used exactly as typed", () => {
  assert.equal(
    applyEdits(BASE, NAMES, { [nameKey(EMPLOYEES)]: '"My Staff" ' }),
    'SELECT name, salary\nFROM "My Staff" \nWHERE salary > 100',
  );
});

test("edits never compound: each call starts from the original text", () => {
  const first = applyEdits(BASE, NAMES, { [nameKey(SALARY)]: "sal" });
  assert.equal(first, "SELECT name, sal\nFROM employees\nWHERE sal > 100");
  assert.equal(applyEdits(BASE, NAMES, { [nameKey(SALARY)]: "salary_usd" }), "SELECT name, salary_usd\nFROM employees\nWHERE salary_usd > 100");
});

test("emoji before a name: spans count code points", () => {
  const base = "SELECT '\u{1F600}' AS e, name FROM people";
  const names = [
    { kind: "column", name: "name", table: "people", spans: [[17, 21]] },
    { kind: "table", name: "people", table: null, spans: [[27, 33]] },
  ];
  assert.equal(
    applyEdits(base, names, { [nameKey(names[0])]: "full_name", [nameKey(names[1])]: "staff" }),
    "SELECT '\u{1F600}' AS e, full_name FROM staff",
  );
});

test("bad spans are skipped, not thrown on", () => {
  const odd = [
    { kind: "column", name: "a", table: null, spans: [[0, 6], [3, 8], [5, 5], [9, 4], [50, 60], [-1, 2], [7, 11]] },
  ];
  assert.equal(applyEdits(BASE, odd, { [nameKey(odd[0])]: "X" }), "X X, salary\nFROM employees\nWHERE salary > 100");
});

test("carryEdits keeps only edits whose name appears again", () => {
  const edits = { [nameKey(SALARY)]: "pay", [nameKey(EMPLOYEES)]: "staff" };
  const next = [{ ...SALARY, spans: [[7, 13]] }, { kind: "table", name: "people", table: null, spans: [[19, 25]] }];
  assert.deepEqual(carryEdits(edits, next), { [nameKey(SALARY)]: "pay" });
  assert.deepEqual(carryEdits(edits, [{ ...SALARY, table: "people" }]), {});
  assert.deepEqual(carryEdits(edits, null), {});
});

test("groupNames puts columns under their table and unstated ones last", () => {
  const total = { kind: "column", name: "total", table: null, spans: [[1, 2]] };
  const orders = { kind: "table", name: "orders", table: null, spans: [[60, 66]] };
  const lost = { kind: "column", name: "x", table: "ghost", spans: [[70, 71]] };
  assert.deepEqual(groupNames([NAME, total, SALARY, EMPLOYEES, orders, lost]), [
    { table: "employees", entry: EMPLOYEES, columns: [NAME, SALARY] },
    { table: "orders", entry: orders, columns: [] },
    { table: "ghost", entry: null, columns: [lost] },
    { table: null, entry: null, columns: [total] },
  ]);
  assert.deepEqual(groupNames(null), []);
  assert.deepEqual(groupNames([EMPLOYEES]), [{ table: "employees", entry: EMPLOYEES, columns: [] }]);
});
