<script>
  import { onMount } from "svelte";
  import SqlEditor from "./components/SqlEditor.svelte";
  import EnglishBox from "./components/EnglishBox.svelte";
  import DocsPanel from "./components/DocsPanel.svelte";
  import { post, latest } from "./lib/api.js";
  import { candidates } from "./lib/position.js";
  import { lookup } from "./lib/docs.js";
  import * as storage from "./lib/storage.js";
  import {
    initial, editSql, editEnglish, setDialect, checkStarted, checkDone,
    applySummary, setVerdict, needsConfirm, summaryOutdated,
  } from "./lib/state.js";

  // Reaches local storage inside a try: a private window can throw on the property access itself.
  function store() {
    try { return window.localStorage; } catch { return null; }
  }

  const FALLBACK_DIALECTS = [
    { id: "postgres", label: "PostgreSQL", exact: true },
    { id: "mysql", label: "MySQL", exact: false },
    { id: "redshift", label: "Redshift", exact: false },
    { id: "athena", label: "Athena", exact: false },
  ];

  const restored = initial(storage.load(store()));
  let s = $state(restored);
  // The SQL box is given its text once, here; the editor never reads this again.
  const startSql = restored.sql;
  let caps = $state(null);
  let pgIndex = $state({ entries: {}, reserved: {} });
  let links = $state({});
  let cursor = $state(0);
  let summaryBusy = $state(false);
  let judgeBusy = $state(false);
  let summaryErr = $state("");
  let judgeErr = $state("");

  const check = latest();
  let timer = null;

  const dialects = $derived(caps && caps.dialects ? caps.dialects : FALLBACK_DIALECTS);
  const dialect = $derived(dialects.find((d) => d.id === s.dialect) || FALLBACK_DIALECTS[0]);
  const summaryOff = $derived(!caps || !caps.summary.available);
  const judgeOff = $derived(!caps || !caps.judge.available);
  const sqlEmpty = $derived(s.sql.trim() === "");
  const englishEmpty = $derived(s.english.trim() === "");
  const docsResult = $derived(
    lookup(s.dialect, candidates(s.sql, cursor), pgIndex, links),
  );

  // The error position handed to the editor; none while the answer is stale.
  const marker = $derived(s.check && !s.check.stale && s.check.error ? s.check.error : null);

  function persist() {
    const st = store();
    if (st) storage.save(st, s);
  }

  // Sends the SQL to the checker and applies the answer unless a newer check replaced it.
  async function runCheck() {
    clearTimeout(timer);
    if (s.sql.trim() === "") {
      s = { ...s, check: null };
      return;
    }
    const sent = { sql: s.sql, dialect: s.dialect };
    s = checkStarted(s);
    const r = await check(post("api/check", sent));
    s = r.ok
      ? checkDone(s, r.data)
      : checkDone(s, { ok: false, exact: dialect.exact, error: null, failure: r.message });
    // An answer for text that has changed since is shown stale.
    if (s.sql !== sent.sql || s.dialect !== sent.dialect) s = checkStarted(s);
  }

  function onSql(text) {
    s = editSql(s, text);
    persist();
    clearTimeout(timer);
    timer = setTimeout(runCheck, 500);
  }

  function onEnglish(text) {
    s = editEnglish(s, text);
    persist();
  }

  function onDialect(e) {
    s = setDialect(s, e.currentTarget.value);
    persist();
    runCheck();
  }

  async function runSummary() {
    if (summaryBusy) return;
    if (needsConfirm(s) && !window.confirm("Replace what you wrote with an AI summary?")) return;
    summaryBusy = true;
    summaryErr = "";
    const sent = { sql: s.sql, dialect: s.dialect };
    const r = await post("api/summary", sent);
    summaryBusy = false;
    if (!r.ok) {
      summaryErr = r.message;
      return;
    }
    s = applySummary(s, r.data);
    persist();
    if (s.sql !== sent.sql || s.dialect !== sent.dialect) s = summaryOutdated(s);
  }

  async function runJudge() {
    if (judgeBusy) return;
    judgeBusy = true;
    judgeErr = "";
    const sent = { sql: s.sql, english: s.english, dialect: s.dialect };
    const r = await post("api/judge", sent);
    judgeBusy = false;
    if (!r.ok) {
      judgeErr = r.message;
      return;
    }
    // Drop the answer when any of the three inputs changed while it was on its way.
    if (s.sql !== sent.sql || s.english !== sent.english || s.dialect !== sent.dialect) return;
    s = setVerdict(s, r.data);
  }

  const tag = (c) => (c.exact ? "exact" : "approximate");
  const syntaxText = $derived.by(() => {
    const c = s.check;
    if (!c) return "";
    if (c.failure) return c.failure;
    if (c.ok) return c.exact ? "OK (exact, PostgreSQL 17 parser)" : "OK (approximate)";
    const e = c.error || {};
    const where = e.line ? `line ${e.line}, col ${e.col}: ` : "";
    return `${where}${e.message} (${tag(c)})`;
  });
  const syntaxClass = $derived(!s.check ? "" : s.check.stale ? "stale" : s.check.failure || !s.check.ok ? "bad" : "ok");

  const choiceText = { agrees: "agrees", differs: "differs", cannot_tell: "cannot tell" };

  onMount(async () => {
    try {
      const res = await fetch("api/caps");
      if (res.ok) caps = await res.json();
    } catch {
      // without caps the dialect list falls back and both AI buttons stay off
    }
    try {
      const [a, b] = await Promise.all([fetch("docs/pg17.json"), fetch("docs/links.json")]);
      if (a.ok) pgIndex = await a.json();
      if (b.ok) links = await b.json();
    } catch {
      // without the docs the panel keeps its hint
    }
    if (s.sql.trim() !== "") runCheck();
  });
</script>

<main>
  <div class="top">
    <label>
      <span class="sr">dialect</span>
      <select value={s.dialect} onchange={onDialect} aria-label="dialect">
        {#each dialects as d}<option value={d.id}>{d.label}</option>{/each}
      </select>
    </label>
  </div>

  <div class="boxes">
    <div class="pane">
      <SqlEditor
        value={startSql}
        dialect={s.dialect}
        error={marker}
        onchange={onSql}
        oncursor={(o) => (cursor = o)}
        onrun={runCheck}
      />
    </div>
    <div class="pane">
      <EnglishBox value={s.english} onchange={onEnglish} />
    </div>
  </div>

  <div class="row">
    <div class="pane">
      <div class="panel">
        <p class="syntax {syntaxClass}" aria-live="polite">{#if s.check}{syntaxText}{#if s.check.stale} checking…{/if}{/if}</p>
        <p class="note">Grammar only: table and column names are not checked.</p>
      </div>
    </div>
    <div class="pane">
      <div class="panel">
        <div class="actions">
          <button
            type="button"
            class="summary-btn"
            disabled={summaryOff || sqlEmpty || summaryBusy}
            aria-busy={summaryBusy}
            onclick={runSummary}
          >{summaryBusy ? "AI summary…" : "AI summary"}</button>
          <button
            type="button"
            class="judge-btn"
            disabled={judgeOff || sqlEmpty || englishEmpty || judgeBusy}
            aria-busy={judgeBusy}
            onclick={runJudge}
          >{judgeBusy ? "Jev: agree?…" : "Jev: agree?"}</button>
        </div>

        {#if caps && !caps.summary.available}
          <p class="line summary-missing">{caps.summary.missing} is not set, so this button is off.</p>
        {/if}
        {#if caps && !caps.judge.available}
          <p class="line judge-missing">{caps.judge.missing} is not set, so this button is off.</p>
        {/if}
        {#if summaryErr}<p class="line err summary-err">{summaryErr}</p>{/if}
        {#if judgeErr}<p class="line err judge-err">{judgeErr}</p>{/if}

        <p class="line origin {s.summaryMeta && s.summaryMeta.stale ? 'stale' : ''}">
          {#if s.origin === "yours"}
            yours
          {:else if s.summaryMeta}
            <b>AI summary</b> · {s.summaryMeta.model} · {s.summaryMeta.input_tokens} in / {s.summaryMeta.output_tokens} out tokens{#if s.summaryMeta.stale} · the SQL has changed since{/if}
          {:else}
            <b>AI summary</b>
          {/if}
        </p>
        {#if s.verdict}
          <p class="line verdict"><b>Jev</b>: {choiceText[s.verdict.choice] || s.verdict.choice} · {Math.round(s.verdict.confidence * 100)}%</p>
        {/if}
      </div>
    </div>
  </div>

  <DocsPanel result={docsResult} dialectLabel={dialect.label} />
</main>

<style>
  .sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); }
</style>
