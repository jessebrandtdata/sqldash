// Writes (or checks) dist/.source-hash: sha256 over web/src, web/index.html, web/public, web/package.json, web/package-lock.json and web/vite.config.js.
// Usage: node scripts/source-hash.js write | check
import { createHash } from "node:crypto";
import { readdirSync, readFileSync, statSync, writeFileSync, existsSync } from "node:fs";
import { join, dirname, relative } from "node:path";
import { fileURLToPath } from "node:url";

const web = join(dirname(fileURLToPath(import.meta.url)), "..");
const dist = join(web, "..", "dist");

function walk(dir, out = []) {
  for (const name of readdirSync(dir).sort()) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p, out);
    else out.push(p);
  }
  return out;
}

const files = [
  ...walk(join(web, "src")),
  join(web, "index.html"),
  ...walk(join(web, "public")),
  join(web, "package.json"),
  join(web, "package-lock.json"),
  join(web, "vite.config.js"),
];
const h = createHash("sha256");
for (const f of files) {
  h.update(relative(web, f) + "\0");
  h.update(readFileSync(f));
  h.update("\0");
}
const digest = h.digest("hex");
const target = join(dist, ".source-hash");

const mode = process.argv[2];
if (mode === "write") {
  writeFileSync(target, digest + "\n");
  console.log("source-hash written", digest.slice(0, 12));
} else if (mode === "check") {
  const recorded = existsSync(target) ? readFileSync(target, "utf8").trim() : "(none)";
  if (recorded !== digest) {
    console.error(`dist is stale (recorded ${recorded.slice(0, 12)}, source ${digest.slice(0, 12)}): run 'npm run build' in web/ and commit dist/`);
    process.exit(1);
  }
  console.log("dist matches source");
} else {
  console.error("usage: source-hash.js write|check");
  process.exit(2);
}
