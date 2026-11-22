import test from "node:test";
import assert from "node:assert/strict";
import { latest, post } from "../src/lib/api.js";

const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const resp = (status, body, raw) => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => { if (raw) throw new SyntaxError("bad"); return body; },
});

test("latest: only the most recent call resolves", async () => {
  const only = latest();
  const hit = [];
  only(new Promise((r) => setTimeout(() => r("old"), 30))).then((v) => hit.push(v));
  only(Promise.resolve("new")).then((v) => hit.push(v));
  await wait(60);
  assert.deepEqual(hit, ["new"]);
});

test("latest: a superseded rejecting call never settles and raises nothing", async () => {
  const unhandled = [];
  const onUnhandled = (e) => unhandled.push(e);
  process.on("unhandledRejection", onUnhandled);
  try {
    const only = latest();
    const seen = [];
    only(new Promise((_, rej) => setTimeout(() => rej(new Error("boom")), 20))).then(
      (v) => seen.push(["ok", v]), (e) => seen.push(["err", e.message]));
    only(Promise.resolve("new")).then((v) => seen.push(["ok", v]));
    await wait(60);
    assert.deepEqual(seen, [["ok", "new"]]);
    assert.deepEqual(unhandled, []);
  } finally {
    process.off("unhandledRejection", onUnhandled);
  }
});

test("latest: the newest call's rejection still rejects", async () => {
  const only = latest();
  await assert.rejects(only(Promise.reject(new Error("x"))), /x/);
});

test("post sends JSON to the path as given", async () => {
  let seen;
  const f = async (url, init) => { seen = [url, init]; return resp(200, { a: 1 }); };
  const r = await post("api/check", { sql: "x" }, f);
  assert.deepEqual(r, { ok: true, data: { a: 1 } });
  assert.equal(seen[0], "api/check");
  assert.equal(seen[1].method, "POST");
  assert.equal(seen[1].headers["Content-Type"], "application/json");
  assert.equal(seen[1].body, JSON.stringify({ sql: "x" }));
});

test("post maps an error body", async () => {
  const f = async () => resp(429, { error: { kind: "rate_limited", message: "slow down" } });
  assert.deepEqual(await post("api/x", {}, f), { ok: false, kind: "rate_limited", message: "slow down" });
});

const INTERNAL = { ok: false, kind: "internal", message: "sqldash's own server gave an answer the page could not read." };

test("post: unreadable answers are internal errors", async () => {
  assert.deepEqual(await post("p", {}, async () => resp(200, null, true)), INTERNAL);
  assert.deepEqual(await post("p", {}, async () => resp(502, null, true)), INTERNAL);
  assert.deepEqual(await post("p", {}, async () => resp(500, { nope: 1 })), INTERNAL);
  assert.deepEqual(await post("p", {}, async () => resp(500, { error: { kind: 1 } })), INTERNAL);
  assert.deepEqual(await post("p", {}, async () => resp(200, "str")), INTERNAL);
});

test("post: a rejected fetch is a network result", async () => {
  const r = await post("p", {}, async () => { throw new TypeError("fail"); });
  assert.deepEqual(r, { ok: false, kind: "network", message: "sqldash's own server could not be reached." });
});
