<script lang="ts">
  import type { Segment } from '../lib/api'
  import { createEventDispatcher } from 'svelte'

  export let segments: Segment[] = []
  export let currentTime: number = 0

  const dispatch = createEventDispatcher<{ seek: number }>()

  $: activeIdx = segments.reduce((found, seg, i) => {
    if (currentTime >= seg.start && currentTime < seg.end) return i
    return found
  }, -1)

  function fmt(s: number): string {
    const t = Math.floor(s)
    return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, '0')}`
  }
</script>

<div class="segments">
  {#each segments as seg, i}
    <button
      class="seg"
      class:active={i === activeIdx}
      on:click={() => dispatch('seek', seg.start)}
    >
      <span class="ts">{fmt(seg.start)}</span>
      <span class="text">{seg.text}</span>
    </button>
  {/each}
</div>

<style>
  .segments {
    display: flex;
    flex-direction: column;
    gap: 2px;
    overflow-y: auto;
    height: 100%;
  }
  .seg {
    display: flex;
    gap: 0.5rem;
    align-items: flex-start;
    text-align: left;
    background: none;
    border: none;
    border-radius: 3px;
    padding: 0.3rem 0.5rem;
    cursor: pointer;
    color: #888;
    font-size: 0.82rem;
    line-height: 1.4;
    transition: background 0.1s, color 0.1s;
  }
  .seg:hover { background: #1a1a1a; color: #ccc; }
  .seg.active { background: #162033; color: #4a9eff; }
  .ts {
    font-family: monospace;
    font-size: 0.75rem;
    color: #555;
    flex-shrink: 0;
    padding-top: 1px;
  }
  .seg.active .ts { color: #4a9eff; opacity: 0.7; }
  .text { flex: 1; }
</style>
