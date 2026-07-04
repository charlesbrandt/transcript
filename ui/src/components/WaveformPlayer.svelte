<script lang="ts">
  import { onMount, onDestroy, createEventDispatcher } from 'svelte'
  import WaveSurfer from 'wavesurfer.js'

  export let src: string
  export let currentTime: number = 0  // two-way: parent can read, seek sets it

  const dispatch = createEventDispatcher<{ seek: number }>()

  let containerEl: HTMLDivElement
  let wavesurfer: WaveSurfer | null = null
  let ready = false
  let playing = false
  let duration = 0

  export function seekTo(seconds: number) {
    wavesurfer?.setTime(seconds)
  }

  function init() {
    ready = false
    playing = false
    if (wavesurfer) { wavesurfer.destroy(); wavesurfer = null }

    wavesurfer = WaveSurfer.create({
      container: containerEl,
      url: src,
      waveColor: '#2e3848',
      progressColor: '#4a9eff',
      cursorColor: '#ffffff',
      cursorWidth: 2,
      height: 80,
      normalize: true,
      backend: 'WebAudio' as const,
    })

    wavesurfer.on('ready', () => {
      duration = wavesurfer!.getDuration()
      ready = true
    })

    wavesurfer.on('timeupdate', (t: number) => {
      currentTime = t
      dispatch('seek', t)
    })

    wavesurfer.on('play', () => (playing = true))
    wavesurfer.on('pause', () => (playing = false))
    wavesurfer.on('finish', () => (playing = false))
  }

  onMount(() => {
    if (src) init()
  })

  onDestroy(() => {
    try { wavesurfer?.pause() } catch (_) {}
    try { wavesurfer?.destroy() } catch (_) {}
  })

  function fmt(s: number): string {
    const t = Math.floor(s)
    return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, '0')}`
  }
</script>

<div class="player">
  <div class="waveform" bind:this={containerEl} />
  <div class="controls">
    <button class="ctrl" on:click={() => wavesurfer?.playPause()} disabled={!ready}>
      {playing ? '⏸' : '▶'}
    </button>
    {#if ready}
      <span class="time">{fmt(currentTime)} / {fmt(duration)}</span>
    {:else}
      <span class="loading">loading waveform…</span>
    {/if}
  </div>
</div>

<style>
  .player {
    background: #0e0e0e;
    border-radius: 4px;
    padding: 0.75rem 1rem;
  }
  .waveform {
    width: 100%;
    min-height: 80px;
    cursor: pointer;
  }
  .controls {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    margin-top: 0.5rem;
  }
  .ctrl {
    background: none;
    border: 1px solid #2a2a2a;
    color: #aaa;
    border-radius: 4px;
    padding: 0.2rem 0.6rem;
    font-size: 0.85rem;
    cursor: pointer;
  }
  .ctrl:hover:not(:disabled) { color: #fff; border-color: #555; }
  .ctrl:disabled { opacity: 0.3; cursor: default; }
  .time {
    font-family: monospace;
    font-size: 0.8rem;
    color: #666;
  }
  .loading { font-size: 0.75rem; color: #444; }
</style>
