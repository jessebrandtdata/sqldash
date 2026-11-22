const DIALECTS = ["postgres", "mysql", "redshift", "athena"];

// Returns a copy of the check result marked stale, or null when there is none.
const staleCheck = (c) => (c ? { ...c, stale: true } : c);
const staleMeta = (m) => (m ? { ...m, stale: true } : m);

// Builds the starting state from saved values, falling back to defaults.
export function initial(saved) {
  const o = saved && typeof saved === "object" ? saved : {};
  return {
    sql: typeof o.sql === "string" ? o.sql : "",
    english: typeof o.english === "string" ? o.english : "",
    dialect: DIALECTS.includes(o.dialect) ? o.dialect : "postgres",
    origin: o.origin === "ai" || o.origin === "yours" ? o.origin : "yours",
    check: null,
    summaryMeta: null,
    verdict: null,
  };
}

export function editSql(s, text) {
  if (text === s.sql) return s;
  return { ...s, sql: text, verdict: null, check: staleCheck(s.check), summaryMeta: staleMeta(s.summaryMeta) };
}

export function editEnglish(s, text) {
  if (text === s.english) return s;
  return { ...s, english: text, origin: "yours", summaryMeta: null, verdict: null };
}

export function setDialect(s, id) {
  return { ...s, dialect: id, verdict: null, check: staleCheck(s.check), summaryMeta: staleMeta(s.summaryMeta) };
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
