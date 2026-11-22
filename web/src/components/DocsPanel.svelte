<script>
  // Shows what lookup() found for the word under the cursor; text goes in as text nodes only.
  let { result, dialectLabel } = $props();
</script>

<section class="panel docs" aria-label="docs">
  {#if !result}
    <p class="note hint">Put the cursor on a keyword or function.</p>
  {:else if result.kind === "link"}
    <p class="doclink">
      <a href={result.url} target="_blank" rel="noopener noreferrer">{result.key} in the {dialectLabel} docs</a>
    </p>
  {:else}
    {#each result.entries as e}
      <article class="entry">
        <h3>{e.title}<span class="kind">{e.kind}</span></h3>
        <pre class="text">{e.text}</pre>
        {#if e.synopsis}<pre class="syn">{e.synopsis}</pre>{/if}
        <a href={e.url} target="_blank" rel="noopener noreferrer">full page</a>
      </article>
    {/each}
    {#if result.reserved}
      <p class="reserved">{result.key}: {result.reserved} in PostgreSQL</p>
    {/if}
  {/if}
</section>
