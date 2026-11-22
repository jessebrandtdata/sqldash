import { applyEdits, carryEdits } from "./names.js";

const DIALECTS = ["postgres", "mysql", "redshift", "athena"];

// Returns a copy of the check result marked stale, or null when there is none.
const staleCheck = (c) => (c ? { ...c, stale: true } : c);
const staleMeta = (m) => (m ? { ...m, stale: true } : m);

// Builds the starting state from saved values, falling back to defaults.
export function initial(saved) {
  const o = saved && typeof saved === "object" ? saved : {};
  const sql = typeof o.sql === "string" ? o.sql : "";
  const toSql = o.direction === "english_to_sql";
  // Edits are kept only as a plain object whose values are all strings.
  const okEdits = o.edits && typeof o.edits === "object" && !Array.isArray(o.edits)
    && Object.values(o.edits).every((v) => typeof v === "string");
  return {
    sql,
    english: typeof o.english === "string" ? o.english : "",
    dialect: DIALECTS.includes(o.dialect) ? o.dialect : "postgres",
    origin: o.origin === "ai" || o.origin === "yours" ? o.origin : "yours",
    check: null,
    summaryMeta: null,
    verdict: null,
    direction: toSql ? "english_to_sql" : "sql_to_english",
    sqlOrigin: o.sqlOrigin === "ai" || o.sqlOrigin === "yours" ? o.sqlOrigin : "yours",
    sqlMeta: null,
    base: toSql ? (typeof o.base === "string" ? o.base : sql) : "",
    names: null,
    namesFailed: false,
    edits: toSql && okEdits ? { ...o.edits } : {},
    note: typeof o.note === "string" ? o.note : "",
  };
}

export function editSql(s, text) {
  if (text === s.sql) return s;
  return { ...s, sql: text, sqlOrigin: "yours", sqlMeta: null, verdict: null, check: staleCheck(s.check), summaryMeta: staleMeta(s.summaryMeta) };
}

export function editEnglish(s, text) {
  if (text === s.english) return s;
  return { ...s, english: text, origin: "yours", summaryMeta: null, sqlMeta: staleMeta(s.sqlMeta), verdict: null };
}

export function setDialect(s, id) {
  return { ...s, dialect: id, verdict: null, check: staleCheck(s.check), summaryMeta: staleMeta(s.summaryMeta), sqlMeta: staleMeta(s.sqlMeta) };
}

export function checkStarted(s) {
  return { ...s, check: staleCheck(s.check) };
}

export function checkDone(s, result) {
  return { ...s, check: { ...result, stale: false } };
}

export function applySummary(s, r) {
  return {
    ...s,
    english: r.text,
    origin: "ai",
    summaryMeta: { model: r.model, input_tokens: r.input_tokens, output_tokens: r.output_tokens, stale: false },
    verdict: null,
  };
}

export function setVerdict(s, r) {
  return { ...s, verdict: { choice: r.choice, confidence: r.confidence } };
}

// True when replacing the English would throw away the user's own words.
export function needsConfirm(s) {
  return s.origin === "yours" && s.english.trim() !== "";
}

// Marks the summary label stale when there is one.
export function summaryOutdated(s) {
  return s.summaryMeta ? { ...s, summaryMeta: staleMeta(s.summaryMeta) } : s;
}

// Marks the generated-SQL label stale when there is one.
export function sqlOutdated(s) {
  return s.sqlMeta ? { ...s, sqlMeta: staleMeta(s.sqlMeta) } : s;
}

// True when replacing the SQL would throw away the user's own SQL.
export function needsSqlConfirm(s) {
  return s.sqlOrigin === "yours" && s.sql.trim() !== "";
}

// True when the SQL is waiting for its names to be read.
export function namesPending(s) {
  return s.direction === "english_to_sql" && s.base.trim() !== "" && s.names === null && !s.namesFailed;
}

// Returns s with sql recomputed from base and edits; a change clears the verdict and stales the check.
function withSql(s, edits) {
  const sql = applyEdits(s.base, s.names, edits);
  if (sql === s.sql) return { ...s, edits };
  return { ...s, edits, sql, verdict: null, check: staleCheck(s.check) };
}

// Takes the answer of api/names for the current base; null or not ok means the names could not be read.
export function applyNames(s, n) {
  if (n && n.ok) {
    const edits = carryEdits(s.edits, n.names);
    return withSql({ ...s, names: n.names, namesFailed: false }, edits);
  }
  return withSql({ ...s, names: null, namesFailed: true }, s.edits);
}

// Takes api/sql's answer r and api/names's answer n for r.sql (or null).
export function applySql(s, r, n) {
  const next = {
    ...s,
    base: r.sql,
    sqlOrigin: "ai",
    sqlMeta: { model: r.model, input_tokens: r.input_tokens, output_tokens: r.output_tokens, stale: false },
    note: r.note,
    verdict: null,
  };
  if (r.sql === "") return { ...next, sql: "", names: null, namesFailed: false, check: null };
  return applyNames({ ...next, check: staleCheck(s.check) }, n);
}

// Stores a name's replacement text as typed, or removes it when text is null.
export function editName(s, key, text) {
  const edits = { ...s.edits };
  if (text === null) delete edits[key];
  else edits[key] = text;
  return withSql(s, edits);
}

// Flips the direction, carrying both texts and clearing what belonged to the old direction.
export function swap(s) {
  const toSql = s.direction === "sql_to_english";
  return {
    ...s,
    direction: toSql ? "english_to_sql" : "sql_to_english",
    base: toSql ? s.sql : "",
    verdict: null,
    note: "",
    names: null,
    namesFailed: false,
    edits: {},
    summaryMeta: s.summaryMeta ? { ...s.summaryMeta, stale: false } : s.summaryMeta,
    sqlMeta: s.sqlMeta ? { ...s.sqlMeta, stale: false } : s.sqlMeta,
  };
}
