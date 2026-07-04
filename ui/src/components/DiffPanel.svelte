<script lang="ts">
  import type { DiffResponse } from '../lib/api'

  export let result: DiffResponse | null = null
  export let loading = false
</script>

<div class="diff">
  {#if loading}
    <span class="hint">Computing diff…</span>
  {:else if !result}
    <span class="hint">Edit the transcript above to see what will be cut.</span>
  {:else}
    <div class="summary">
      <span class="keep">▪ {result.kept_count} kept</span>
      <span class="remove">▪ {result.removed_count} removed</span>
      <span class="saved">▪ {result.time_saved}s saved ({result.time_saved_pct}%)</span>
    </div>
    <div class="words">
      {#each result.aligned_words as w}
        <span class="word {w.status === 'KEEP' ? 'keep' : 'remove'}" title="{w.start.toFixed(2)}s–{w.end.toFixed(2)}s">{w.word}</span>
      {/each}
    </div>
  {/if}
</div>

<style>
  .diff {
    font-size: 0.82rem;
    line-height: 1.6;
  }
  .hint { color: #555; font-style: italic; }
  .summary {
    display: flex;
    gap: 1rem;
    margin-bottom: 0.5rem;
    font-size: 0.78rem;
    font-family: monospace;
  }
  .summary .keep { color: #5a9; }
  .summary .remove { color: #c55; }
  .summary .saved { color: #888; }
  .words { line-height: 1.7; }
  .word {
    display: inline;
    margin-right: 0.2em;
    border-radius: 2px;
    padding: 0 2px;
  }
  .word.keep { color: #ccc; }
  .word.remove {
    color: #c55;
    text-decoration: line-through;
    background: rgba(200, 50, 50, 0.12);
  }
</style>
