<script>
  import { onMount } from "svelte";
  import SqlEditor from "./components/SqlEditor.svelte";
  import EnglishBox from "./components/EnglishBox.svelte";
  import DocsPanel from "./components/DocsPanel.svelte";
  import NameBoxes from "./components/NameBoxes.svelte";
  import { post, latest } from "./lib/api.js";
  import { candidates } from "./lib/position.js";
  import { lookup } from "./lib/docs.js";
  import * as storage from "./lib/storage.js";
  import {
    initial, editSql, editEnglish, setDialect, checkStarted, checkDone,
    applySummary, setVerdict, needsConfirm, summaryOutdated,
    applySql, applyNames, editName, swap, needsSqlConfirm, sqlOutdated, namesPending,
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
  let caps = $state(null);
  let pgIndex = $state({ entries: {}, reserved: {} });
  let links = $state({});
  let cursor = $state(0);
  let summaryBusy = $state(false);
  let judgeBusy = $state(false);
  let sqlBusy = $state(false);
  let summaryErr = $state("");
  let judgeErr = $state("");
  let sqlErr = $state("");
  let namesErr = $state("");

  const check = latest();
  let timer = null;

  const dialects = $derived(caps && caps.dialects ? caps.dialects : FALLBACK_DIALECTS);
  const dialect = $derived(dialects.find((d) => d.id === s.dialect) || FALLBACK_DIALECTS[0]);
  const summaryOff = $derived(!caps || !caps.summary.available);
  const judgeOff = $derived(!caps || !caps.judge.available);
  const sqlOff = $derived(!caps || !caps.sql.available);
  const toSql = $derived(s.direction === "english_to_sql");
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
      // An empty box supersedes any check still in flight, so an old answer never lands.
      await check(Promise.resolve(null));
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
    summaryErr = "";
    judgeErr = "";
    sqlErr = "";
    s = editSql(s, text);
    persist();
    clearTimeout(timer);
    timer = setTimeout(runCheck, 500);
  }

  function onEnglish(text) {
    summaryErr = "";
    judgeErr = "";
    sqlErr = "";
    s = editEnglish(s, text);
    persist();
  }

  function onDialect(e) {
    summaryErr = "";
    judgeErr = "";
    sqlErr = "";
    s = setDialect(s, e.currentTarget.value);
    persist();
    if (toSql && s.base.trim() !== "") readNames();
    runCheck();
  }

  // Reads the names of the SQL as generated; the answer is dropped when the direction, text or dialect moved on.
  async function readNames() {
    namesErr = "";
    const sent = { direction: s.direction, base: s.base, dialect: s.dialect };
    const r = await post("api/names", { sql: sent.base, dialect: sent.dialect });
    if (s.direction !== sent.direction || s.base !== sent.base || s.dialect !== sent.dialect) return;
    if (!r.ok) {
      namesErr = r.message;
      return;
    }
    s = applyNames(s, r.data);
    persist();
    runCheck();
  }

  // Flips the direction and carries both texts across; no model is called.
  function onSwap() {
    if (summaryBusy || sqlBusy || judgeBusy) return;
    summaryErr = "";
    judgeErr = "";
    sqlErr = "";
    namesErr = "";
    s = swap(s);
    persist();
    cursor = 0;
    if (namesPending(s)) readNames();
    runCheck();
  }

  // Edits one name; the syntax check follows after the same pause as typing.
  function onName(key, text) {
    summaryErr = "";
    judgeErr = "";
    sqlErr = "";
    s = editName(s, key, text);
    persist();
    clearTimeout(timer);
    timer = setTimeout(runCheck, 500);
  }

  async function runWrite() {
    if (sqlBusy) return;
    if (needsSqlConfirm(s) && !window.confirm("Replace the SQL you wrote with AI-written SQL?")) return;
    sqlBusy = true;
    sqlErr = "";
    namesErr = "";
    const sent = { english: s.english, dialect: s.dialect };
    const r = await post("api/sql", sent);
    if (!r.ok) {
      sqlErr = r.message;
      sqlBusy = false;
      return;
    }
    let names = null;
    if (r.data.sql !== "") {
      const n = await post("api/names", { sql: r.data.sql, dialect: sent.dialect });
      names = n.ok ? n.data : null;
      if (!n.ok) namesErr = n.message;
    }
    s = applySql(s, r.data, names);
    persist();
    if (s.english !== sent.english || s.dialect !== sent.dialect) s = sqlOutdated(s);
    if (s.dialect !== sent.dialect && s.base.trim() !== "") readNames();
    sqlBusy = false;
    runCheck();
  }

  async function runSummary() {
    if (summaryBusy) return;
    if (needsConfirm(s) && !window.confirm("Replace what you wrote with an AI summary?")) return;
    summaryBusy = true;
    summaryErr = "";
    const sent = { sql: s.sql, dialect: s.dialect };
    const englishSent = s.english;
    const r = await post("api/summary", sent);
    summaryBusy = false;
    if (!r.ok) {
      summaryErr = r.message;
      return;
    }
    // Words typed while the request was out are asked about again before they are replaced.
    if (s.english !== englishSent && needsConfirm(s) && !window.confirm("Replace what you wrote with an AI summary?")) return;
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
    if (namesPending(s)) readNames();
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
      {#if toSql}
        <EnglishBox value={s.english} onchange={onEnglish} />
      {:else}
        <SqlEditor
          value={s.sql}
          dialect={s.dialect}
          error={marker}
          onchange={onSql}
          oncursor={(o) => (cursor = o)}
          onrun={runCheck}
        />
      {/if}
    </div>
    <button
      type="button"
      class="swap-btn"
      aria-label="swap direction"
      disabled={summaryBusy || sqlBusy || judgeBusy}
      onclick={onSwap}
    >⇄</button>
    <div class="pane">
      {#if toSql}
        <SqlEditor
          readonly
          value={s.sql}
          dialect={s.dialect}
          error={marker}
          onchange={onSql}
          oncursor={(o) => (cursor = o)}
          onrun={runCheck}
        />
      {:else}
        <EnglishBox value={s.english} onchange={onEnglish} />
      {/if}
    </div>
  </div>

  {#snippet syntaxLines()}
    <p class="syntax {syntaxClass}" aria-live="polite">{#if s.check}{syntaxText}{#if s.check.stale} checking…{/if}{/if}</p>
    <p class="note">Grammar only: table and column names are not checked.</p>
  {/snippet}

  {#snippet jevLines()}
    {#if caps && !caps.judge.available}
      <p class="line judge-missing">{caps.judge.missing} is not set, so this button is off.</p>
    {/if}
    {#if judgeErr}<p class="line err judge-err">{judgeErr}</p>{/if}
  {/snippet}

  {#snippet jevButton()}
    <button
      type="button"
      class="judge-btn"
      disabled={judgeOff || sqlEmpty || englishEmpty || judgeBusy}
      aria-busy={judgeBusy}
      onclick={runJudge}
    >{judgeBusy ? "Jev: agree?…" : "Jev: agree?"}</button>
  {/snippet}

  {#snippet verdictLine()}
    {#if s.verdict}
      <p class="line verdict"><b>Jev</b>: {choiceText[s.verdict.choice] || s.verdict.choice} · {Math.round(s.verdict.confidence * 100)}%</p>
    {/if}
  {/snippet}

  <div class="row">
    <div class="pane">
      <div class="panel">
        {#if toSql}
          <div class="actions">
            <button
              type="button"
              class="write-btn"
              disabled={sqlOff || englishEmpty || sqlBusy}
              aria-busy={sqlBusy}
              onclick={runWrite}
            >{sqlBusy ? "Write SQL…" : "Write SQL"}</button>
            {@render jevButton()}
          </div>
          {#if caps && !caps.sql.available}
            <p class="line sql-missing">{caps.sql.missing} is not set, so this button is off.</p>
          {/if}
          {@render jevLines()}
          {#if sqlErr}<p class="line err sql-err">{sqlErr}</p>{/if}
          {@render verdictLine()}
        {:else}
          {@render syntaxLines()}
        {/if}
      </div>
    </div>
    <div class="gap"></div>
    <div class="pane">
      <div class="panel">
        {#if toSql}
          {@render syntaxLines()}
          {#if s.sql !== ""}
            <p class="line sql-origin {s.sqlMeta && s.sqlMeta.stale ? 'stale' : ''}">
              {#if s.sqlOrigin === "yours"}
                yours
              {:else if s.sqlMeta}
                <b>AI SQL</b> · {s.sqlMeta.model} · {s.sqlMeta.input_tokens} in / {s.sqlMeta.output_tokens} out tokens{#if s.sqlMeta.stale} · the description has changed since{/if}
              {:else}
                <b>AI SQL</b>
              {/if}
            </p>
          {/if}
          {#if s.note !== ""}<p class="note sql-note">{s.note}</p>{/if}
          {#if namesErr}<p class="line err names-err">{namesErr}</p>{/if}
          <NameBoxes names={s.names} edits={s.edits} failed={s.namesFailed} onedit={onName} />
        {:else}
          <div class="actions">
            <button
              type="button"
              class="summary-btn"
              disabled={summaryOff || sqlEmpty || summaryBusy}
              aria-busy={summaryBusy}
              onclick={runSummary}
            >{summaryBusy ? "AI summary…" : "AI summary"}</button>
            {@render jevButton()}
          </div>

          {#if caps && !caps.summary.available}
            <p class="line summary-missing">{caps.summary.missing} is not set, so this button is off.</p>
          {/if}
          {@render jevLines()}
          {#if summaryErr}<p class="line err summary-err">{summaryErr}</p>{/if}

          {#if s.english !== ""}
          <p class="line origin {s.summaryMeta && s.summaryMeta.stale ? 'stale' : ''}">
            {#if s.origin === "yours"}
              yours
            {:else if s.summaryMeta}
              <b>AI summary</b> · {s.summaryMeta.model} · {s.summaryMeta.input_tokens} in / {s.summaryMeta.output_tokens} out tokens{#if s.summaryMeta.stale} · the SQL has changed since{/if}
            {:else}
              <b>AI summary</b>
            {/if}
          </p>
          {/if}
          {@render verdictLine()}
        {/if}
      </div>
    </div>
  </div>

  <DocsPanel result={docsResult} dialectLabel={dialect.label} />
</main>

<style>
  .sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); }
</style>
