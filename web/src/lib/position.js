// Maps a 1-based line and column to a 0-based offset, clamped to the text.
export function lineColToOffset(text, line, col) {
  let start = 0;
  // Walk forward one line break at a time until the wanted line starts.
  for (let l = 1; l < line; l++) {
    const nl = text.indexOf("\n", start);
    if (nl === -1) return text.length;
    start = nl + 1;
  }
  let end = text.indexOf("\n", start);
  if (end === -1) end = text.length;
  // A CR before the line break is part of the break, not the line.
  if (end > start && text[end - 1] === "\r") end -= 1;
  const offset = start + Math.max(col, 1) - 1;
  return Math.min(offset, end);
}

const isStart = (c) => /[A-Za-z_]/.test(c);
const isWord = (c) => /[A-Za-z0-9_]/.test(c);

// Scans the text once and returns the words plus the spans the cursor must not be in.
function scan(text) {
  const words = [];
  const dead = [];
  let i = 0;
  const n = text.length;
  while (i < n) {
    const c = text[i];
    if (c === "'" || c === '"') {
      // A quoted run ends at the next lone quote; a doubled quote is an escape.
      let j = i + 1;
      while (j < n) {
        if (text[j] === c) {
          if (text[j + 1] === c) { j += 2; continue; }
          break;
        }
        j++;
      }
      const end = j < n ? j + 1 : n;
      dead.push([i, end, "open"]);
      i = end;
    } else if (c === "-" && text[i + 1] === "-") {
      let j = text.indexOf("\n", i);
      if (j === -1) j = n;
      dead.push([i, j, "closed"]);
      i = j;
    } else if (c === "/" && text[i + 1] === "*") {
      const j = text.indexOf("*/", i + 2);
      const end = j === -1 ? n : j + 2;
      dead.push([i, end, "open"]);
      i = end;
    } else if (isStart(c)) {
      let j = i + 1;
      while (j < n && isWord(text[j])) j++;
      words.push({ start: i, end: j, text: text.slice(i, j).toUpperCase() });
      i = j;
    } else if (isWord(c)) {
      // A digit run (with trailing letters) is a token, not a word.
      let j = i + 1;
      while (j < n && isWord(text[j])) j++;
      i = j;
    } else {
      i++;
    }
  }
  return { words, dead };
}

// Returns upper-cased phrases around the word at the cursor, longest first.
export function candidates(text, offset) {
  offset = Math.max(0, Math.min(offset, text.length));
  const { words, dead } = scan(text);
  for (const [s, e, kind] of dead) {
    // A string or block comment holds offsets strictly between its ends.
    if (kind === "open" && offset > s && offset < e) return [];
    // A line comment also holds the offset at its very end.
    if (kind === "closed" && offset > s && offset <= e) return [];
  }
  const at = words.findIndex((w) => offset >= w.start && offset <= w.end);
  if (at === -1) return [];
  // Two neighbours are joined only when nothing but blanks lies between them.
  const joined = (a, b) => /^[ \t\r\n]*$/.test(text.slice(words[a].end, words[b].start));
  const out = [];
  for (const len of [3, 2, 1]) {
    for (let first = at; first > at - len; first--) {
      const last = first + len - 1;
      if (first < 0 || last >= words.length) continue;
      let ok = true;
      for (let k = first; k < last; k++) if (!joined(k, k + 1)) ok = false;
      if (ok) out.push(words.slice(first, last + 1).map((w) => w.text).join(" "));
    }
  }
  return out;
}
