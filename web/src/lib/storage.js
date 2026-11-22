const KEY = "sqldash.v1";

// Reads the saved fields, or null when anything is missing or unreadable.
export function load(store) {
  try {
    const raw = store.getItem(KEY);
    if (raw == null) return null;
    const v = JSON.parse(raw);
    return v && typeof v === "object" && !Array.isArray(v) ? v : null;
  } catch {
    return null;
  }
}

// Writes the nine saved fields and ignores every failure.
export function save(store, state) {
  try {
    const { sql, english, dialect, origin, direction, sqlOrigin, base, edits, note } = state;
    store.setItem(KEY, JSON.stringify({ sql, english, dialect, origin, direction, sqlOrigin, base, edits, note }));
  } catch {
    // A blocked or full store only means nothing is remembered.
  }
}
