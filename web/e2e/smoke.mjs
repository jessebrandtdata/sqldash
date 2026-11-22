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

// Starts ./serve on a free port and resolves with the child and its base URL.
async function startServer() {
  const port = await freePort();
  const env = { ...process.env, SQLDASH_ENV: "/dev/null" };
  for (const k of ["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "TYPESAFE_API_KEY"]) delete env[k];
  const child = spawn(join(root, "serve"), ["127.0.0.1", String(port)], { cwd: root, env, stdio: ["ignore", "pipe", "pipe"] });
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

async function main() {
  const matches = await buildMatcher();
  const { child, base } = await startServer();
  let browser;
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
      if (/api\/(summary|judge)/.test(req.url())) aiRequests.push(req.url());
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
    ok(7, "no request to api/summary or api/judge");
    console.log("smoke ok");
  } finally {
    if (browser) await browser.close().catch(() => {});
    child.kill("SIGTERM");
  }
}

main().catch((e) => {
  console.error(e.message || e);
  process.exit(1);
});
