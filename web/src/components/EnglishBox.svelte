<script>
  // Plain textarea; the user can type here at any time.
  let { value, onchange } = $props();
</script>

<textarea
  class="english"
  aria-label="English"
  {value}
  oninput={(e) => onchange(e.currentTarget.value)}
></textarea>

<style>
  .english {
    width: 100%;
    height: 18rem;
    resize: vertical;
    padding: 0.5rem 0.7rem;
    border: 1px solid var(--sd-edge);
    border-radius: 6px;
    background: var(--sd-bg);
    color: var(--sd-text);
    font: inherit;
    line-height: 1.45;
  }
</style>
