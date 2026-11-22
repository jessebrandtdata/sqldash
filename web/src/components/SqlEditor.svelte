<script>
  import { onMount } from "svelte";
  import { EditorView, keymap, lineNumbers, highlightActiveLine } from "@codemirror/view";
  import { EditorState, Compartment } from "@codemirror/state";
  import { defaultKeymap, history, historyKeymap } from "@codemirror/commands";
  import { syntaxHighlighting, HighlightStyle } from "@codemirror/language";
  import { tags as t } from "@lezer/highlight";
  import { sql, PostgreSQL, MySQL, StandardSQL } from "@codemirror/lang-sql";
  import { linter, lintGutter, setDiagnostics } from "@codemirror/lint";
  import { lineColToOffset } from "../lib/position.js";

  // `value` is read once, at mount; after that only the user's typing changes the text.
  let { value, dialect, error, onchange, oncursor, onrun } = $props();

  let host;
  let view;
  const language = new Compartment();

  // Token colours come from the page tokens so light, dark and the served theme all read well.
  const highlight = HighlightStyle.define([
    { tag: [t.keyword, t.operatorKeyword], color: "var(--sd-accent)", fontWeight: "600" },
    { tag: [t.string, t.special(t.string)], color: "var(--sd-ok)" },
    { tag: [t.number, t.bool, t.null], color: "var(--sd-bad)" },
    { tag: [t.comment, t.lineComment, t.blockComment], color: "var(--sd-dim)", fontStyle: "italic" },
    { tag: [t.typeName, t.standard(t.name)], color: "var(--sd-accent)" },
  ]);

  const dialects = { postgres: PostgreSQL, redshift: PostgreSQL, mysql: MySQL, athena: StandardSQL };
  const langFor = (id) => sql({ dialect: dialects[id] || PostgreSQL });

  // Builds the one lint diagnostic for an error position, or none.
  function diagnostics(text, err) {
    if (!err || !err.line || !err.col) return [];
    const from = lineColToOffset(text, err.line, err.col);
    let to;
    if (err.end_col) {
      to = lineColToOffset(text, err.line, err.end_col);
    } else {
      to = from;
      while (to < text.length && /[A-Za-z0-9_]/.test(text[to])) to++;
    }
    if (to <= from) to = Math.min(from + 1, text.length);
    if (to <= from) return [];
    return [{ from, to, severity: "error", message: err.message || "syntax error" }];
  }

  onMount(() => {
    view = new EditorView({
      parent: host,
      state: EditorState.create({
        doc: value,
        extensions: [
          lineNumbers(),
          highlightActiveLine(),
          history(),
          syntaxHighlighting(highlight),
          language.of(langFor(dialect)),
          linter(null),
          lintGutter(),
          EditorView.lineWrapping,
          keymap.of([
            { key: "Mod-Enter", run: () => { onrun(); return true; } },
            ...defaultKeymap,
            ...historyKeymap,
          ]),
          EditorView.updateListener.of((u) => {
            if (u.docChanged) onchange(u.state.doc.toString());
            if (u.docChanged || u.selectionSet) oncursor(u.state.selection.main.head);
          }),
          EditorView.contentAttributes.of({ "aria-label": "SQL" }),
        ],
      }),
    });
    oncursor(view.state.selection.main.head);
    return () => view.destroy();
  });

  // Switches the highlighting when the dialect changes.
  $effect(() => {
    const id = dialect;
    if (view) view.dispatch({ effects: language.reconfigure(langFor(id)) });
  });

  // Shows the error marker, or clears it.
  $effect(() => {
    const err = error;
    if (view) view.dispatch(setDiagnostics(view.state, diagnostics(view.state.doc.toString(), err)));
  });
</script>

<div class="sql" bind:this={host}></div>

<style>
  .sql {
    height: 18rem;
    border: 1px solid var(--sd-edge);
    border-radius: 6px;
    background: var(--sd-bg);
    overflow: hidden;
  }
  .sql :global(.cm-editor) { height: 100%; background: var(--sd-bg); color: var(--sd-text); }
  .sql :global(.cm-scroller) { font-family: var(--sd-mono); font-size: 0.9rem; overflow: auto; }
  .sql :global(.cm-gutters) { background: var(--sd-panel); color: var(--sd-dim); border-right: 1px solid var(--sd-edge); }
  .sql :global(.cm-activeLine) { background: transparent; }
  .sql :global(.cm-cursor) { border-left-color: var(--sd-text); }
  .sql :global(.cm-focused) { outline: 2px solid var(--sd-accent); }
</style>
