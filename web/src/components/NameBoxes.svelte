<script>
  import { groupNames, nameKey } from "../lib/names.js";

  // One input per table and column name; text goes in as values and text nodes only.
  let { names, edits, failed, onedit } = $props();

  const groups = $derived(groupNames(names));

  const valueOf = (n) => (nameKey(n) in edits ? edits[nameKey(n)] : n.name);
  const labelOf = (n) => {
    if (n.kind === "table") return `table ${n.name}`;
    return n.table === null ? `column ${n.name}, table not stated` : `column ${n.name} of ${n.table}`;
  };
  // An emptied box goes back to the original name.
  const blurred = (n, e) => {
    if (e.currentTarget.value.trim() === "") onedit(nameKey(n), null);
  };
</script>

{#snippet box(n)}
  <input
    class="name-box"
    type="text"
    data-kind={n.kind}
    data-name={n.name}
    placeholder={n.name}
    aria-label={labelOf(n)}
    value={valueOf(n)}
    oninput={(e) => onedit(nameKey(n), e.currentTarget.value)}
    onblur={(e) => blurred(n, e)}
  />
{/snippet}

{#if failed}
  <p class="note names-failed">The names in this SQL could not be read.</p>
{:else if names && names.length}
  <section class="names" aria-label="names">
    <h3>Names</h3>
    {#each groups as g (JSON.stringify([g.table]))}
      <div class="name-group">
        {#if g.table === null}
          <p class="group-head">table not stated</p>
        {:else if g.entry}
          {@render box(g.entry)}
        {:else}
          <p class="group-head">{g.table}</p>
        {/if}
        {#if g.columns.length}
          <div class="name-cols">
            {#each g.columns as c (nameKey(c))}{@render box(c)}{/each}
          </div>
        {/if}
      </div>
    {/each}
  </section>
{/if}

<style>
  .names { margin-top: 0.7rem; }
  .names h3 { margin: 0 0 0.4rem; font-size: 1rem; }
  .name-group { margin-bottom: 0.5rem; }
  .group-head { margin: 0 0 0.25rem; color: var(--sd-dim); font-size: 0.85rem; }
  .name-cols { margin-left: 1.5rem; display: flex; flex-direction: column; gap: 0.25rem; margin-top: 0.25rem; }
  .name-box {
    display: block;
    width: 100%;
    max-width: 24rem;
    padding: 0.2rem 0.5rem;
    /* An input's default line height clips the underscore of a name at 1x. */
    line-height: 1.5;
    border: 1px solid var(--sd-edge);
    border-radius: 4px;
    background: var(--sd-bg);
    color: var(--sd-text);
    font-family: var(--sd-mono);
    font-size: 0.9rem;
  }
</style>
