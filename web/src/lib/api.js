// Wraps calls so only the most recently started one ever settles.
export function latest() {
  let current = 0;
  return (promise) => {
    const mine = ++current;
    return new Promise((resolve, reject) => {
      Promise.resolve(promise).then(
        (v) => { if (mine === current) resolve(v); },
        (e) => { if (mine === current) reject(e); },
      );
    });
  };
}

const INTERNAL = {
  ok: false,
  kind: "internal",
  message: "sqldash's own server gave an answer the page could not read.",
};

// Posts JSON and returns a result object; it never throws.
export async function post(path, body, fetchImpl = fetch) {
  let res;
  try {
    res = await fetchImpl(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    return { ok: false, kind: "network", message: "sqldash's own server could not be reached." };
  }
  let data;
  try {
    data = await res.json();
  } catch {
    return { ...INTERNAL };
  }
  if (res.ok) return data === null || typeof data !== "object" ? { ...INTERNAL } : { ok: true, data };
  const e = data && data.error;
  if (e && typeof e.kind === "string" && typeof e.message === "string") {
    return { ok: false, kind: e.kind, message: e.message };
  }
  return { ...INTERNAL };
}
