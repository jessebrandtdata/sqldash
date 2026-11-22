// Builds the key that identifies a name across parses: kind, table and name.
export function nameKey(name) {
  return JSON.stringify([name.kind, name.table, name.name]);
}

// Returns base with every span of every edited name replaced by the edit's text.
export function applyEdits(base, names, edits) {
  if (!names || !names.length) return base;
  // Map each code point index to its UTF-16 offset, with the text length last.
  const offsets = [];
  for (let i = 0; i < base.length; i += base.codePointAt(i) > 0xffff ? 2 : 1) offsets.push(i);
  const count = offsets.length;
  offsets.push(base.length);
  // Collect one replacement per span of each name that has a non-blank edit.
  const reps = [];
  for (const n of names) {
    const text = edits[nameKey(n)];
    if (typeof text !== "string" || text.trim() === "") continue;
    for (const [start, end] of n.spans || []) {
      if (!(start >= 0 && end > start && end <= count)) continue;
      reps.push({ start: offsets[start], end: offsets[end], text });
    }
  }
  // Apply in order from one sorted list, skipping any span that overlaps the last kept one.
  reps.sort((a, b) => a.start - b.start);
  let out = "";
  let pos = 0;
  for (const r of reps) {
    if (r.start < pos) continue;
    out += base.slice(pos, r.start) + r.text;
    pos = r.end;
  }
  return out + base.slice(pos);
}

// Keeps the edits whose key is the key of some name in names.
export function carryEdits(edits, names) {
  const keys = new Set((names || []).map(nameKey));
  const out = {};
  for (const [k, v] of Object.entries(edits || {})) {
    if (keys.has(k)) out[k] = v;
  }
  return out;
}

// Groups names by table: tables in order, then unlisted tables, then columns with no table.
export function groupNames(names) {
  const list = names || [];
  const groups = [];
  const byTable = new Map();
  // One group per table name, in the order tables appear.
  for (const n of list) {
    if (n.kind !== "table") continue;
    const g = { table: n.name, entry: n, columns: [] };
    groups.push(g);
    if (!byTable.has(n.name)) byTable.set(n.name, g);
  }
  const loose = [];
  // File each column under its table, creating an entry-less group when the table is not named.
  for (const n of list) {
    if (n.kind !== "column") continue;
    if (n.table === null) {
      loose.push(n);
      continue;
    }
    let g = byTable.get(n.table);
    if (!g) {
      g = { table: n.table, entry: null, columns: [] };
      groups.push(g);
      byTable.set(n.table, g);
    }
    g.columns.push(n);
  }
  if (loose.length) groups.push({ table: null, entry: null, columns: loose });
  return groups;
}
