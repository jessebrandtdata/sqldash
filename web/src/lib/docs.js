// Finds the docs for the first matching candidate, or returns null.
export function lookup(dialect, candidates, pgIndex, links) {
  const entries = pgIndex.entries || {};
  const reserved = pgIndex.reserved || {};
  const has = (o, k) => Object.prototype.hasOwnProperty.call(o, k);
  if (dialect === "postgres") {
    for (const key of candidates) {
      if (has(entries, key)) {
        return { kind: "entries", key, entries: entries[key], reserved: has(reserved, key) ? reserved[key] : null };
      }
    }
    for (const key of candidates) {
      if (has(reserved, key)) return { kind: "entries", key, entries: [], reserved: reserved[key] };
    }
    return null;
  }
  const d = links[dialect];
  if (!d) return null;
  for (const key of candidates) {
    if (d.pages && has(d.pages, key)) return { kind: "link", key, url: d.pages[key] };
  }
  for (const key of candidates) {
    if (has(entries, key)) {
      return { kind: "link", key, url: d.search.replace("{q}", encodeURIComponent(key)) };
    }
  }
  return null;
}
