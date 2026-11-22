// Headless-browser smoke test: starts ./serve, drives the page, checks seven things.
// Host-only; not part of `check`. Usage: node web/e2e/smoke.mjs
import { spawn } from "node:child_process";
import { createServer } from "node:net";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright-core";

const root = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const cacheDir = join(homedir(), ".cache", "sqldash");
const listFile = join(cacheDir, "easyprivacy.txt");
const LIST_URL = "https://easylist.to/easylist/easyprivacy.txt";
const FRAGMENTS = ["stat", "track", "collect", "pixel", "beacon", "analytics", "pageview", "ads"];

// Finds a free TCP port by binding port 0 and closing again.
function freePort() {
  return new Promise((resolve, reject) => {
    const srv = createServer();
    srv.on("error", reject);
    srv.listen(0, "127.0.0.1", () => {
      const { port } = srv.address();
      srv.close(() => resolve(port));
    });
  });
}

// Returns the filter list text, from the cache or one download; null when neither works.
async function filterListText() {
  if (existsSync(listFile)) return readFileSync(listFile, "utf8");
  try {
    const res = await fetch(LIST_URL, { signal: AbortSignal.timeout(30000) });
    if (!res.ok) throw new Error(String(res.status));
    const text = await res.text();
    mkdirSync(cacheDir, { recursive: true });
    writeFileSync(listFile, text);
    return text;
  } catch {
    return null;
  }
}

const escapeRe = (s) => s.replace(/[.+?${}()|[\]\\]/g, "\\$&");

// Turns one list line into a RegExp, or null when the line is not a generic URL rule.
function ruleToRegExp(line) {
  line = line.trim();
  if (!line || line.startsWith("!") || line.startsWith("[") || line.startsWith("@@")) return null;
  if (line.includes("##") || line.includes("#@#") || line.includes("#?#") || line.includes("#$#")) return null;
  const dollar = line.lastIndexOf("$");
  if (dollar !== -1) {
    // A third-party-only rule cannot match this page's own first-party requests.
    const options = line.slice(dollar + 1).split(",");
    if (options.includes("third-party") || options.includes("3p")) return null;
    line = line.slice(0, dollar);
  }
  // A rule that is empty or only wildcards would block everything.
  if (!line || /^\*+$/.test(line) || (line.startsWith("/") && line.endsWith("/") && line.length > 2)) return null;
  let head = "";
  if (line.startsWith("||")) { head = "^[a-z][a-z0-9+.-]*://([^/]*\\.)?"; line = line.slice(2); }
  else if (line.startsWith("|")) { head = "^"; line = line.slice(1); }
  let tail = "";
  if (line.endsWith("|")) { tail = "$"; line = line.slice(0, -1); }
  if (!line) return null;
  const body = escapeRe(line).replace(/\*/g, ".*").replace(/\^/g, "(?:[^\\w.%-]|$)");
  try {
    return new RegExp(head + body + tail, "i");
  } catch {
    return null;
  }
}

// Builds the URL matcher from the list, or from the eight blocked fragments without it.
async function buildMatcher() {
  const text = await filterListText();
  if (text === null) {
    console.log("filter list unavailable and not cached: using the eight blocked fragments only");
    const re = new RegExp(FRAGMENTS.join("|"), "i");
    return (url) => re.test(url);
  }
  const rules = text.split("\n").map(ruleToRegExp).filter(Boolean);
  console.log(`filter list: ${rules.length} URL rules`);
  return (url) => rules.some((re) => re.test(url));
}

// Starts a server command on a free port and resolves with the child and its base URL.
async function startServer(cmd = join(root, "serve"), extra = []) {
  const port = await freePort();
  const env = { ...process.env, SQLDASH_ENV: "/dev/null" };
  for (const k of ["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "TYPESAFE_API_KEY"]) delete env[k];
  const child = spawn(cmd, [...extra, ...(extra.length ? [String(port)] : ["127.0.0.1", String(port)])], { cwd: root, env, stdio: ["ignore", "pipe", "pipe"] });
  let log = "";
  child.stderr.on("data", (d) => { log += d; });
  const base = await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("server did not start in 20 s: " + log)), 20000);
    let out = "";
    child.stdout.on("data", (d) => {
      out += d;
      const m = out.match(/sqldash on (http:\/\/\S+)/);
      if (m) { clearTimeout(timer); resolve(m[1] + "/"); }
    });
    child.on("exit", (code) => { clearTimeout(timer); reject(new Error(`server exited ${code}: ${log}`)); });
  });
  return { child, base };
}

function ok(n, what) {
  console.log(`ok ${n} ${what}`);
}

function assert(cond, message) {
  if (!cond) throw new Error(message);
}

const norm = (t) => t.replace(/\s+/g, " ").trim();

// Assertions 8 to 15: the AI buttons against the fake services, light scheme.
async function aiPass(browser, matches, base) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 }, colorScheme: "light" });
  const page = await context.newPage();
  await page.route("**/*", (route) => (matches(route.request().url()) ? route.abort() : route.continue()));
  // An empty theme.css leaves the page on its literal light fallback colours.
  await page.route("**/theme.css", (route) => route.fulfill({ status: 200, contentType: "text/css", body: "" }));
  let summaryCount = 0;
  page.on("request", (req) => { if (/api\/summary/.test(req.url())) summaryCount++; });
  const dialogs = [];
  let dialogAction = "accept";
  page.on("dialog", (d) => {
    dialogs.push(d.message());
    return dialogAction === "accept" ? d.accept() : d.dismiss();
  });
  const editor = page.locator(".cm-content");
  const english = page.locator(".english");
  const label = page.locator(".origin");
  const summaryBtn = page.locator(".summary-btn");
  const verdict = page.locator(".verdict");
  const labelText = async () => (await label.count() ? norm(await label.textContent()) : "");
  const waitLabel = (part) => page.waitForFunction(
    (t) => (document.querySelector(".origin")?.textContent || "").replace(/\s+/g, " ").includes(t),
    part,
    { timeout: 10000 },
  ).catch(async () => { throw new Error(`label never showed "${part}"; it shows "${await labelText()}"`); });
  const waitEnabled = () => page.waitForFunction(
    () => { const b = document.querySelector(".summary-btn"); return b && !b.disabled; },
    null,
    { timeout: 10000 },
  );
  const replaceSql = async (text) => {
    await editor.click();
    await page.keyboard.press("Control+A");
    await page.keyboard.type(text);
  };
  const appendSql = async (text) => {
    await editor.click();
    await page.keyboard.press("Control+End");
    await page.keyboard.type(text);
  };

  await page.goto(base);
  await editor.waitFor();

  // 8: summary fills the English box and the label, with no confirm for an empty box
  await replaceSql("select a from t");
  await summaryBtn.click();
  await page.waitForFunction(() => document.querySelector(".english").value === "It reads t.", null, { timeout: 10000 })
    .catch(async () => { throw new Error(`English box holds "${await english.inputValue()}"`); });
  await waitLabel("AI summary · fake-model · 11 in / 7 out tokens");
  assert(dialogs.length === 0, `a confirm appeared for an empty box: ${dialogs}`);
  ok(8, "AI summary fills the English box and the label; no confirm for an empty box");

  // 9: Jev verdict shows choice, percent and name
  await page.locator(".judge-btn").click();
  await verdict.waitFor({ timeout: 10000 });
  const v = norm(await verdict.textContent());
  assert(v.includes("Jev") && v.includes("differs") && v.includes("87%"), `verdict shows "${v}"`);
  ok(9, `Jev verdict shows "${v}"`);
  const shots = process.env.SQLDASH_SMOKE_SHOTS;
  if (shots) {
    mkdirSync(shots, { recursive: true });
    await page.screenshot({ path: join(shots, "page-ai.png") });
  }

  // 10: editing the SQL clears the verdict and marks the label
  await appendSql(" where a = 1");
  await page.waitForFunction(() => !document.querySelector(".verdict"), null, { timeout: 5000 });
  await waitLabel("· the SQL has changed since");
  ok(10, "editing the SQL removes the verdict and marks the label");

  // 11: typing English makes the label `yours`; the confirm guards the replacement
  await english.click();
  await page.keyboard.press("Control+End");
  await page.keyboard.type("!");
  await page.waitForFunction(() => (document.querySelector(".origin")?.textContent || "").trim() === "yours");
  dialogAction = "dismiss";
  const before = summaryCount;
  await summaryBtn.click();
  await page.waitForTimeout(600);
  assert(dialogs.length === 1 && dialogs[0] === "Replace what you wrote with an AI summary?", `dialogs: ${JSON.stringify(dialogs)}`);
  assert((await english.inputValue()) === "It reads t.!", "dismissing the confirm changed the English box");
  assert(summaryCount === before, "dismissing the confirm still sent a request");
  dialogAction = "accept";
  await summaryBtn.click();
  await page.waitForFunction(() => document.querySelector(".english").value === "It reads t.", null, { timeout: 10000 });
  assert(dialogs.length === 2 && dialogs[1] === dialogs[0], "accepting did not raise the same confirm");
  await waitEnabled();
  ok(11, "label reads yours after typing; confirm text exact; dismiss changes and sends nothing; accept replaces");

  // 12 and 14: a slow answer for changed SQL arrives marked stale; the busy button takes no second request
  await replaceSql("select slow from t");
  const c0 = summaryCount;
  await summaryBtn.click();
  const busyDisabled = await summaryBtn.isDisabled();
  await summaryBtn.click({ force: true, timeout: 2000 }).catch(() => {});
  await appendSql(" ");
  await page.waitForTimeout(300);
  await waitEnabled();
  await waitLabel("· the SQL has changed since");
  const sent = summaryCount - c0;
  ok(12, "answer arriving after an SQL edit shows '· the SQL has changed since' at once");

  // 13: a refusal shows its sentence, leaves the English alone, and clears on the next attempt
  await english.click();
  await page.keyboard.press("Control+End");
  await page.keyboard.type("mine");
  await replaceSql("select refuse from t");
  await summaryBtn.click();
  const err = page.locator(".summary-err");
  await err.waitFor({ timeout: 10000 });
  assert(norm(await err.textContent()) === "The model declined to answer for this text.", `error shows "${await err.textContent()}"`);
  assert((await english.inputValue()) === "It reads t.mine", `English changed to "${await english.inputValue()}"`);
  await replaceSql("select a from t");
  await summaryBtn.click();
  await page.waitForFunction(() => !document.querySelector(".summary-err"), null, { timeout: 5000 });
  await page.waitForFunction(() => document.querySelector(".english").value === "It reads t.", null, { timeout: 10000 });
  ok(13, "refusal sentence shown, English unchanged, cleared by the next attempt");

  // 14: reported after 13 so the numbers read in order
  assert(busyDisabled, "the button was not disabled while a request was in flight");
  assert(sent === 1, `expected 1 api/summary request during the in-flight window, saw ${sent}`);
  ok(14, "button disabled while in flight and no second request");

  // 15: only the keyboard touched the SQL box
  await waitEnabled();
  const finalSql = await editor.textContent();
  assert(finalSql === "select a from t", `SQL box holds "${finalSql}"`);
  ok(15, "SQL box holds exactly what was typed");

  // 15b: words typed while a summary loads are asked about again when the answer arrives
  await replaceSql("select slow from t");
  await english.click();
  await page.keyboard.press("Control+End");
  await page.keyboard.type("x");
  await page.waitForFunction(() => (document.querySelector(".origin")?.textContent || "").trim() === "yours");
  dialogAction = "accept";
  const d0 = dialogs.length;
  await summaryBtn.click();
  assert(dialogs.length === d0 + 1, `the pre-send confirm did not appear: ${JSON.stringify(dialogs.slice(d0))}`);
  await english.click();
  await page.keyboard.press("Control+End");
  await page.keyboard.type("yy");
  dialogAction = "dismiss";
  await waitEnabled();
  assert(dialogs.length === d0 + 2 && dialogs[d0 + 1] === dialogs[0], `no second confirm on arrival: ${JSON.stringify(dialogs.slice(d0))}`);
  const kept = await english.inputValue();
  assert(kept === "It reads t.xyy", `English holds "${kept}" after the summary was dismissed`);
  ok("15b", "words typed during the request survive a dismissed confirm on arrival");

  // Assertions 16 to 26: English to SQL, the swap and the name boxes.
  const counts = { sql: 0, summary: 0, judge: 0, names: 0, check: 0 };
  let judgeBody = null;
  page.on("request", (req) => {
    const m = req.url().match(/api\/(sql|summary|judge|names|check)\b/);
    if (!m) return;
    counts[m[1]]++;
    if (m[1] === "judge") judgeBody = req.postData();
  });
  const swapBtn = page.locator(".swap-btn");
  const writeBtn = page.locator(".write-btn");
  const origin = page.locator(".sql-origin");
  const right = ".sql.readonly .cm-content";
  const linesOf = (sel) => page.evaluate(
    (s) => Array.from(document.querySelectorAll(s + " .cm-line")).map((l) => l.textContent).join("\n"),
    sel,
  );
  const waitRight = (text) => page.waitForFunction(
    ([s, t]) => Array.from(document.querySelectorAll(s + " .cm-line")).map((l) => l.textContent).join("\n") === t,
    [right, text],
    { timeout: 10000 },
  ).catch(async () => { throw new Error(`right box never held ${JSON.stringify(text)}; it holds ${JSON.stringify(await linesOf(right))}`); });
  const waitWriteEnabled = () => page.waitForFunction(
    () => { const b = document.querySelector(".write-btn"); return b && !b.disabled; },
    null,
    { timeout: 10000 },
  );
  const settledSyntax = (text) => page.waitForFunction(
    (t) => {
      const el = document.querySelector(".syntax");
      return el && el.textContent.includes(t) && !el.textContent.includes("checking");
    },
    text,
    { timeout: 10000 },
  ).catch(async () => { throw new Error(`syntax line never showed "${text}"; it shows "${await page.locator(".syntax").textContent()}"`); });
  const boxNames = () => page.locator(".name-box").evaluateAll((els) => els.map((e) => `${e.dataset.kind}:${e.dataset.name}`));
  const nameBox = (name) => page.locator(`.name-box[data-name="${name}"]`);
  const originText = async () => (await origin.count() ? norm(await origin.textContent()) : "");
  const waitOrigin = (text) => page.waitForFunction(
    (t) => (document.querySelector(".sql-origin")?.textContent || "").replace(/\s+/g, " ").trim().includes(t),
    text,
    { timeout: 10000 },
  ).catch(async () => { throw new Error(`sql label never showed "${text}"; it shows "${await originText()}"`); });
  const FAKE_SQL = "SELECT name, salary\nFROM employees\nWHERE salary > 100";
  const PAY_SQL = "SELECT name, pay\nFROM employees\nWHERE pay > 100";
  const shotDir = process.env.SQLDASH_SMOKE_SHOTS;

  // 16: swap carries both texts and calls no model
  await replaceSql("select a from t");
  await english.fill("some words here");
  const m0 = { sql: counts.sql, summary: counts.summary, judge: counts.judge };
  await swapBtn.click();
  await page.waitForFunction(() => document.querySelector(".sql.readonly"), null, { timeout: 5000 });
  assert((await english.inputValue()) === "some words here", `left box holds "${await english.inputValue()}"`);
  assert((await linesOf(right)) === "select a from t", `right box holds "${await linesOf(right)}"`);
  await nameBox("a").waitFor({ timeout: 10000 });
  const b16 = await boxNames();
  assert(b16.join() === "table:t,column:a", `name boxes are ${b16}`);
  assert((await originText()) === "yours", `sql label reads "${await originText()}"`);
  assert(counts.sql === m0.sql && counts.summary === m0.summary && counts.judge === m0.judge, "swap called a model route");
  ok(16, "swap carries both texts, shows boxes for t and a, label yours, no model route called");

  // 17: Write SQL asks before replacing the user's own SQL
  await english.fill("people paid over 100");
  dialogAction = "dismiss";
  const dl = dialogs.length;
  await writeBtn.click();
  await page.waitForTimeout(600);
  assert(dialogs.length === dl + 1 && dialogs[dl] === "Replace the SQL you wrote with AI-written SQL?", `dialogs: ${JSON.stringify(dialogs.slice(dl))}`);
  assert(counts.sql === m0.sql, "dismissing the confirm still sent a request");
  assert((await linesOf(right)) === "select a from t", "dismissing the confirm changed the right box");
  dialogAction = "accept";
  await writeBtn.click();
  await waitRight(FAKE_SQL);
  await waitWriteEnabled();
  await waitOrigin("AI SQL");
  assert((await originText()) === "AI SQL · fake-sql-model · 13 in / 9 out tokens", `sql label reads "${await originText()}"`);
  await settledSyntax("OK (exact, PostgreSQL 17 parser)");
  await nameBox("salary").waitFor({ timeout: 10000 });
  const b17 = await boxNames();
  assert(b17.join() === "table:employees,column:name,column:salary", `name boxes are ${b17}`);
  ok(17, "Write SQL confirms first, then shows three lines, the label, OK syntax and the names");

  // 18: a name edit changes every occurrence and re-checks
  const k0 = { check: counts.check, sql: counts.sql, summary: counts.summary, judge: counts.judge };
  await nameBox("salary").fill("pay");
  await waitRight(PAY_SQL);
  await settledSyntax("OK (exact");
  assert(counts.check === k0.check + 1, `expected 1 more api/check, saw ${counts.check - k0.check}`);
  assert(counts.sql === k0.sql && counts.summary === k0.summary && counts.judge === k0.judge, "a name edit called a model route");
  await nameBox("salary").fill("");
  await waitRight(FAKE_SQL);
  await nameBox("salary").blur();
  assert((await nameBox("salary").inputValue()) === "salary", `cleared box shows "${await nameBox("salary").inputValue()}"`);
  await nameBox("salary").fill("pay");
  await waitRight(PAY_SQL);
  await settledSyntax("OK (exact");
  if (shotDir) {
    mkdirSync(shotDir, { recursive: true });
    await page.screenshot({ path: join(shotDir, "e2s-wide.png"), fullPage: true });
  }
  ok(18, "renaming salary to pay changes both places and re-checks; clearing restores it; no model route");

  // 19: editing the description marks the SQL
  await english.click();
  await page.keyboard.press("Control+End");
  await page.keyboard.type(" now");
  await waitOrigin("· the description has changed since");
  ok(19, "editing the description marks the AI SQL label");

  // 20: a second Write SQL replaces model-written SQL without asking and re-applies the edit
  const d20 = dialogs.length;
  const s20 = counts.sql;
  await writeBtn.click();
  await page.waitForFunction(() => document.querySelector(".write-btn")?.disabled, null, { timeout: 2000 }).catch(() => {});
  await waitWriteEnabled();
  await waitRight(PAY_SQL);
  assert(dialogs.length === d20, `a dialog appeared: ${JSON.stringify(dialogs.slice(d20))}`);
  assert(counts.sql === s20 + 1, `expected 1 more api/sql, saw ${counts.sql - s20}`);
  assert((await nameBox("salary").inputValue()) === "pay", `salary box shows "${await nameBox("salary").inputValue()}"`);
  assert(!(await originText()).includes("has changed since"), `label still stale: "${await originText()}"`);
  ok(20, "second Write SQL asks nothing, sends one request, re-applies pay");

  // 21: Jev works in this direction
  await settledSyntax("OK (exact");
  await page.locator(".judge-btn").click();
  await verdict.waitFor({ timeout: 10000 });
  const v21 = norm(await verdict.textContent());
  assert(v21.includes("differs") && v21.includes("87%"), `verdict shows "${v21}"`);
  const sentSql = JSON.parse(judgeBody).sql;
  assert(sentSql === PAY_SQL, `Jev was sent ${JSON.stringify(sentSql)}`);
  await nameBox("salary").fill("pays");
  await page.waitForFunction(() => !document.querySelector(".verdict"), null, { timeout: 5000 });
  await nameBox("salary").fill("pay");
  await waitRight(PAY_SQL);
  await settledSyntax("OK (exact");
  ok(21, "Jev shows differs · 87% on the SQL as shown; a name edit removes the verdict");

  // 22: reload restores it
  await page.reload();
  await page.locator(".sql.readonly .cm-content").waitFor();
  await nameBox("salary").waitFor({ timeout: 10000 });
  await waitRight(PAY_SQL);
  assert((await nameBox("salary").inputValue()) === "pay", `salary box shows "${await nameBox("salary").inputValue()}"`);
  assert((await english.inputValue()) === "people paid over 100 now", `description holds "${await english.inputValue()}"`);
  assert((await originText()) === "AI SQL", `sql label reads "${await originText()}"`);
  ok(22, "reload restores the description, the pay SQL, the direction, the pay box and the AI SQL label");

  // 23: a vague description and a refusal
  await english.fill("vague");
  await writeBtn.click();
  await page.locator(".sql-note").waitFor({ timeout: 10000 });
  await waitWriteEnabled();
  assert(norm(await page.locator(".sql-note").textContent()) === "Say which table to read.", "vague note is wrong");
  assert((await linesOf(right)) === "", `right box holds "${await linesOf(right)}"`);
  assert((await page.locator(".name-box").count()) === 0, "name boxes remain for an empty SQL");
  assert((await page.locator(".syntax").textContent()).trim() === "", `syntax line reads "${await page.locator(".syntax").textContent()}"`);
  await english.fill("refuse");
  await writeBtn.click();
  await page.locator(".sql-err").waitFor({ timeout: 10000 });
  assert(norm(await page.locator(".sql-err").textContent()) === "The model declined to answer for this text.", "refusal sentence is wrong");
  await waitWriteEnabled();
  assert((await linesOf(right)) === "" && norm(await page.locator(".sql-note").textContent()) === "Say which table to read.", "a refusal changed the page");
  ok(23, "vague shows the note and no boxes; refuse shows its sentence and changes nothing else");

  // 24: swap back puts the shown SQL on the left as plain text
  await english.fill("people paid over 100");
  await writeBtn.click();
  await waitRight(PAY_SQL);
  await waitWriteEnabled();
  await swapBtn.click();
  await editor.waitFor({ timeout: 5000 });
  assert((await linesOf(".cm-content")) === PAY_SQL, `editor holds "${await linesOf(".cm-content")}"`);
  assert((await page.locator(".names").count()) === 0 && (await page.locator(".name-box").count()) === 0, "name boxes remain after swapping back");
  assert((await english.inputValue()) === "people paid over 100", `English box holds "${await english.inputValue()}"`);
  await appendSql(" limit 5");
  const typed = await linesOf(".cm-content");
  assert(typed === PAY_SQL + " limit 5", `editor holds "${typed}" after typing`);
  await swapBtn.click();
  await page.waitForFunction(() => document.querySelector(".sql.readonly"), null, { timeout: 5000 });
  await swapBtn.click();
  await editor.waitFor({ timeout: 5000 });
  assert((await linesOf(".cm-content")) === typed && (await english.inputValue()) === "people paid over 100", "two more swaps changed the texts");
  ok(24, "swap back shows the SQL as plain text on the left; two more swaps keep both texts");

  // 25: while Write SQL is in flight both buttons are off and a second click sends nothing
  await swapBtn.click();
  await page.waitForFunction(() => document.querySelector(".sql.readonly"), null, { timeout: 5000 });
  await english.fill("slow people");
  dialogAction = "accept";
  const s25 = counts.sql;
  await writeBtn.click();
  const wOff = await writeBtn.isDisabled();
  const sOff = await swapBtn.isDisabled();
  await writeBtn.click({ force: true, timeout: 2000 }).catch(() => {});
  await waitWriteEnabled();
  assert(wOff && sOff, `during the request write disabled=${wOff}, swap disabled=${sOff}`);
  assert(counts.sql === s25 + 1, `expected 1 api/sql request, saw ${counts.sql - s25}`);
  ok(25, "Write SQL and swap are disabled in flight and no second request goes out");

  // 25b: a Write SQL answer that lands after the description changed is marked stale at once
  await english.fill("slow people again");
  await writeBtn.click();
  await english.click();
  await page.keyboard.press("Control+End");
  await page.keyboard.type(" more");
  await waitWriteEnabled();
  await waitOrigin("· the description has changed since");
  assert((await linesOf(right)) === FAKE_SQL, `right box holds "${await linesOf(right)}"`);
  ok("25b", "a late Write SQL answer is marked as outdated at once and the right box holds the fake SQL");

  // 26: narrow layout puts the swap button between the boxes
  await page.setViewportSize({ width: 500, height: 900 });
  await page.waitForTimeout(200);
  const rects = await page.evaluate(() => {
    const r = (el) => { const b = el.getBoundingClientRect(); return { top: b.top, bottom: b.bottom }; };
    const panes = document.querySelectorAll(".boxes > .pane");
    return { a: r(panes[0]), btn: r(document.querySelector(".swap-btn")), b: r(panes[panes.length - 1]) };
  });
  assert(rects.a.bottom <= rects.btn.top && rects.btn.bottom <= rects.b.top, `swap button is not between the boxes: ${JSON.stringify(rects)}`);
  if (shotDir) await page.screenshot({ path: join(shotDir, "e2s-narrow.png"), fullPage: true });
  ok(26, "at 500 px the swap button lies between the two boxes");

  // 27: a names request that fails in transport shows its sentence, no boxes and no names-failed line
  await page.setViewportSize({ width: 1280, height: 800 });
  await swapBtn.click();
  await editor.waitFor({ timeout: 5000 });
  await page.route("**/api/names", (route) => route.abort());
  await swapBtn.click();
  await page.locator(".names-err").waitFor({ timeout: 10000 });
  assert(norm(await page.locator(".names-err").textContent()) === "sqldash's own server could not be reached.", `names-err reads "${await page.locator(".names-err").textContent()}"`);
  assert((await page.locator(".name-box").count()) === 0, "name boxes appear after a failed names request");
  assert((await page.locator(".names-failed").count()) === 0, "the names-failed line appeared for a transport failure");
  assert((await linesOf(right)) === FAKE_SQL, `right box holds "${await linesOf(right)}"`);
  await page.unroute("**/api/names");
  await page.selectOption("select", "mysql");
  await nameBox("salary").waitFor({ timeout: 10000 });
  await page.selectOption("select", "postgres");
  await nameBox("salary").waitFor({ timeout: 10000 });
  assert((await page.locator(".names-err").count()) === 0, "names-err stays after a good names request");
  ok(27, "a failed names request shows its own sentence and no boxes; changing the dialect reads the names again");
  await context.close();
}

async function main() {
  const matches = await buildMatcher();
  const { child, base } = await startServer();
  let browser;
  let second = null;
  try {
    browser = await chromium.launch({
      headless: true,
      env: { ...process.env, LD_LIBRARY_PATH: join(homedir(), "dev/bullets/web/tests/.libs/usr/lib/x86_64-linux-gnu") },
    });
    const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
    const aborted = [];
    const aiRequests = [];
    await page.route("**/*", (route) => {
      const url = route.request().url();
      if (matches(url)) {
        aborted.push(url);
        return route.abort();
      }
      return route.continue();
    });
    page.on("request", (req) => {
      if (/api\/(summary|judge|sql)/.test(req.url())) aiRequests.push(req.url());
    });
    const syntax = page.locator(".syntax");
    const settled = (text) => page.waitForFunction(
      (t) => {
        const el = document.querySelector(".syntax");
        return el && el.textContent.includes(t) && !el.textContent.includes("checking");
      },
      text,
      { timeout: 10000 },
    ).catch(async () => {
      throw new Error(`syntax line never showed "${text}"; it shows "${await syntax.textContent()}"`);
    });
    const editor = page.locator(".cm-content");

    // 1: a doubled comma is reported at line 1, col 10, exact, with a lint marker
    await page.goto(base);
    await editor.waitFor();
    await editor.click();
    await page.keyboard.type("select a,, b from t");
    await settled("line 1, col 10");
    const t1 = await syntax.textContent();
    assert(t1.includes("(exact)"), `expected "(exact)" in "${t1}"`);
    await page.locator(".cm-lintRange-error").first().waitFor({ timeout: 5000 }).catch(() => {
      throw new Error("no lint marker in the editor");
    });
    ok(1, "typed error shows line 1, col 10, (exact) and a lint marker");

    // 1b: the focused SQL box shows a caret in the text colour and a focus ring that is not clipped
    const seen = await page.evaluate(() => {
      const content = document.querySelector(".cm-content");
      const box = document.querySelector(".sql");
      return {
        caret: getComputedStyle(content).caretColor,
        text: getComputedStyle(content).color,
        ring: getComputedStyle(box).outlineStyle,
        ringWidth: parseFloat(getComputedStyle(box).outlineWidth),
      };
    });
    assert(seen.caret === seen.text, `SQL caret is ${seen.caret} but the text is ${seen.text}`);
    assert(seen.ring !== "none" && seen.ringWidth >= 1, `focused SQL box has no ring (outline ${seen.ring} ${seen.ringWidth}px)`);
    ok("1b", "focused SQL box shows its caret in the text colour and a focus ring");

    // 2: MySQL verdicts are approximate
    await page.selectOption("select", "mysql");
    await settled("(approximate)");
    ok(2, "MySQL shows (approximate)");

    // 3: both AI buttons are off and name their missing variable
    const buttons = [page.locator(".summary-btn"), page.locator(".judge-btn")];
    for (const b of buttons) assert(await b.isDisabled(), "an AI button is enabled without its key");
    const body = await page.locator("main").textContent();
    assert(body.includes("ANTHROPIC_API_KEY is not set"), "page lacks 'ANTHROPIC_API_KEY is not set'");
    assert(body.includes("TYPESAFE_API_KEY is not set"), "page lacks 'TYPESAFE_API_KEY is not set'");
    ok(3, "both AI buttons disabled with their missing-key sentences");

    // 4: cursor inside coalesce shows its docs entry and the PostgreSQL 17 link
    await page.selectOption("select", "postgres");
    await editor.click();
    await page.keyboard.press("Control+A");
    await page.keyboard.type("select coalesce(a, b) from t");
    await page.keyboard.press("Home");
    for (let i = 0; i < 10; i++) await page.keyboard.press("ArrowRight");
    await page.waitForFunction(() => document.querySelector(".docs")?.textContent.includes("COALESCE"), null, { timeout: 5000 })
      .catch(async () => { throw new Error(`docs panel shows "${await page.locator(".docs").textContent()}"`); });
    const hrefs = await page.locator(".docs a").evaluateAll((as) => as.map((a) => a.href));
    assert(hrefs.some((h) => h.includes("postgresql.org/docs/17/")), `no docs/17 link among ${JSON.stringify(hrefs)}`);
    ok(4, "docs panel shows COALESCE with a postgresql.org/docs/17/ link");

    const shots = process.env.SQLDASH_SMOKE_SHOTS;
    if (shots) {
      mkdirSync(shots, { recursive: true });
      await settled("OK (exact");
      await page.screenshot({ path: join(shots, "page.png") });
      await page.setViewportSize({ width: 600, height: 900 });
      await page.screenshot({ path: join(shots, "page-narrow.png"), fullPage: true });
      await page.setViewportSize({ width: 1280, height: 800 });
    }

    // 5: a reload restores the SQL text
    await page.reload();
    await editor.waitFor();
    const restored = await editor.textContent();
    assert(restored === "select coalesce(a, b) from t", `after reload the SQL box holds "${restored}"`);
    ok(5, "SQL box restored after reload");

    // 6: the filter list aborted nothing
    assert(aborted.length === 0, `filter list aborted: ${aborted.join(", ")}`);
    ok(6, "no request was aborted by the filter list");

    // 7: no AI request was made
    assert(aiRequests.length === 0, `AI requests seen: ${aiRequests.join(", ")}`);
    ok(7, "no request to api/summary, api/judge or api/sql");

    // 3b: Write SQL is off without its key and names the missing variable; swap, look, swap back
    await page.locator(".swap-btn").click();
    await page.locator(".write-btn").waitFor({ timeout: 5000 });
    assert(await page.locator(".write-btn").isDisabled(), "Write SQL is enabled without its key");
    const missing = norm(await page.locator(".sql-missing").textContent());
    assert(missing === "ANTHROPIC_API_KEY is not set, so this button is off.", `sql-missing reads "${missing}"`);
    await page.locator(".swap-btn").click();
    await editor.waitFor({ timeout: 5000 });
    assert(aiRequests.length === 0, `AI requests seen after swapping: ${aiRequests.join(", ")}`);
    ok("3b", "Write SQL is off with ANTHROPIC_API_KEY named; swapping sends no AI request");

    // 7b: an unfinished statement is reported at the end of the text, with a lint marker
    await editor.click();
    await page.keyboard.press("Control+A");
    await page.keyboard.type("select (");
    await settled("line 1, col 9: syntax error at end of input (exact)");
    await page.locator(".cm-lintRange-error").first().waitFor({ timeout: 5000 }).catch(() => {
      throw new Error("no lint marker for the end-of-input error");
    });
    ok("7b", "typing 'select (' shows line 1, col 9: syntax error at end of input (exact) and a lint marker");

    // Second pass: the same page against fake services, in a light colour scheme.
    child.kill("SIGTERM");
    const fake = await startServer("python3", [join(root, "web", "e2e", "fake_server.py")]);
    second = fake.child;
    await aiPass(browser, matches, fake.base);
    console.log("smoke ok");
  } finally {
    if (browser) await browser.close().catch(() => {});
    child.kill("SIGTERM");
    if (second) second.kill("SIGTERM");
  }
}

main().catch((e) => {
  console.error(e.message || e);
  process.exit(1);
});
