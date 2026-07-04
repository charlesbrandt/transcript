<script lang="ts">
  import { onMount } from 'svelte'
  import WaveformPlayer from './components/WaveformPlayer.svelte'
  import SegmentList from './components/SegmentList.svelte'
  import DiffPanel from './components/DiffPanel.svelte'
  import {
    loadSession,
    fetchDiff,
    streamRender,
    streamRetranscribe,
    mediaUrl,
    type SessionResponse,
    type DiffResponse,
    type SseEvent,
  } from './lib/api'

  type Phase = 'idle' | 'loading' | 'ready' | 'rendering' | 'retranscribing'

  let metadataInput = ''
  let phase: Phase = 'idle'
  let error = ''
  let session: SessionResponse | null = null
  let editText = ''
  let currentTime = 0
  let diffResult: DiffResponse | null = null
  let diffLoading = false
  let renderProgress: string[] = []
  let renderOutputPath: string | null = null
  let padding = 0.1

  let player: WaveformPlayer | null = null

  // Parse ?metadata= query param on load
  onMount(() => {
    const params = new URLSearchParams(window.location.search)
    const m = params.get('metadata')
    if (m) {
      metadataInput = m
      loadFile()
    }
  })

  async function loadFile() {
    if (!metadataInput.trim()) return
    phase = 'loading'
    error = ''
    session = null
    diffResult = null
    renderOutputPath = null
    renderProgress = []

    try {
      session = await loadSession(metadataInput.trim())
      editText = session.edit_text
      phase = 'ready'
      // Update URL
      const url = new URL(window.location.href)
      url.searchParams.set('metadata', metadataInput.trim())
      window.history.replaceState(null, '', url.toString())
      // Trigger initial diff
      triggerDiff()
    } catch (e) {
      error = e instanceof Error ? e.message : String(e)
      phase = 'idle'
    }
  }

  let diffTimer: ReturnType<typeof setTimeout> | null = null

  function onEditInput() {
    diffResult = null
    if (diffTimer) clearTimeout(diffTimer)
    diffTimer = setTimeout(triggerDiff, 600)
  }

  async function triggerDiff() {
    if (!session) return
    diffLoading = true
    try {
      diffResult = await fetchDiff(session.metadata_path, editText)
    } catch (_) {
      // non-fatal; diff panel just stays blank
    } finally {
      diffLoading = false
    }
  }

  function onSegmentSeek(e: CustomEvent<number>) {
    player?.seekTo(e.detail)
  }

  function onPlayerSeek(e: CustomEvent<number>) {
    currentTime = e.detail
  }

  function doRender() {
    if (!session || phase !== 'ready') return
    phase = 'rendering'
    renderProgress = ['Starting render…']
    renderOutputPath = null

    streamRender(session.metadata_path, editText, padding, (ev: SseEvent) => {
      if (ev.type === 'progress') {
        renderProgress = [...renderProgress, ev.message]
      } else if (ev.type === 'done') {
        renderOutputPath = (ev as { type: 'done'; output_path?: string }).output_path ?? null
        renderProgress = [...renderProgress, 'Done.']
        phase = 'ready'
      } else if (ev.type === 'error') {
        renderProgress = [...renderProgress, `Error: ${ev.message}`]
        phase = 'ready'
      }
    })
  }

  function doRetranscribe() {
    if (!session || phase !== 'ready') return
    phase = 'retranscribing'
    renderProgress = ['Starting retranscription…']

    streamRetranscribe(session.metadata_path, (ev: SseEvent) => {
      if (ev.type === 'progress') {
        renderProgress = [...renderProgress, ev.message]
      } else if (ev.type === 'done') {
        renderProgress = [...renderProgress, 'Done — reload to edit the new transcript.']
        phase = 'ready'
      } else if (ev.type === 'error') {
        renderProgress = [...renderProgress, `Error: ${ev.message}`]
        phase = 'ready'
      }
    })
  }
</script>

<div class="app">
  <header>
    <h1>Transcript Editor</h1>
  </header>

  <div class="loader">
    <input
      class="path-input"
      type="text"
      placeholder="/absolute/path/to/file-metadata.json"
      bind:value={metadataInput}
      on:keydown={e => e.key === 'Enter' && loadFile()}
    />
    <button class="btn" on:click={loadFile} disabled={phase === 'loading'}>
      {phase === 'loading' ? 'Loading…' : 'Load'}
    </button>
  </div>

  {#if error}
    <div class="error">{error}</div>
  {/if}

  {#if session}
    <div class="waveform-wrap">
      {#if session.media_path}
        <WaveformPlayer
          bind:this={player}
          src={mediaUrl(session.media_path)}
          bind:currentTime
          on:seek={onPlayerSeek}
        />
      {:else}
        <div class="no-media">No media file found alongside metadata.</div>
      {/if}
    </div>

    <div class="main">
      <div class="left">
        <h3>Segments</h3>
        <SegmentList
          segments={session.segments}
          {currentTime}
          on:seek={onSegmentSeek}
        />
      </div>

      <div class="right">
        <div class="edit-section">
          <h3>Edit transcript <span class="hint">— delete words or lines to cut them</span></h3>
          <textarea
            class="edit-area"
            bind:value={editText}
            on:input={onEditInput}
            spellcheck={false}
          />
        </div>

        <div class="diff-section">
          <h3>Diff preview</h3>
          <DiffPanel result={diffResult} loading={diffLoading} />
        </div>
      </div>
    </div>

    <div class="footer">
      <label class="padding-label">
        Padding (s):
        <input type="number" min="0" max="2" step="0.05" bind:value={padding} class="padding-input" />
      </label>
      <button
        class="btn primary"
        on:click={doRender}
        disabled={phase !== 'ready'}
      >
        {phase === 'rendering' ? 'Rendering…' : 'Render'}
      </button>
      {#if renderOutputPath}
        <button
          class="btn"
          on:click={doRetranscribe}
          disabled={phase !== 'ready'}
        >
          {phase === 'retranscribing' ? 'Retranscribing…' : 'Retranscribe'}
        </button>
      {/if}

      {#if renderProgress.length}
        <div class="progress">
          {#each renderProgress as line}
            <div>{line}</div>
          {/each}
        </div>
      {/if}

      {#if renderOutputPath}
        <div class="output">
          <strong>Output:</strong> {renderOutputPath}
          <WaveformPlayer src={mediaUrl(renderOutputPath)} currentTime={0} />
        </div>
      {/if}
    </div>
  {/if}
</div>

<style>
  :global(*, *::before, *::after) { box-sizing: border-box; }

  :global(body) {
    margin: 0;
    font-family: system-ui, -apple-system, sans-serif;
    background: #111;
    color: #ddd;
  }

  .app {
    min-height: 100vh;
    display: flex;
    flex-direction: column;
  }

  header {
    padding: 0.75rem 1.5rem;
    background: #1a1a1a;
    border-bottom: 1px solid #333;
  }

  h1 {
    margin: 0;
    font-size: 1.2rem;
    font-weight: 600;
    letter-spacing: 0.05em;
    color: #4a9eff;
  }

  h3 {
    margin: 0 0 0.4rem;
    font-size: 0.78rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #555;
  }

  .loader {
    display: flex;
    gap: 0.5rem;
    padding: 0.75rem 1rem;
    background: #161616;
    border-bottom: 1px solid #222;
  }

  .path-input {
    flex: 1;
    background: #0e0e0e;
    border: 1px solid #333;
    border-radius: 4px;
    color: #ccc;
    padding: 0.4rem 0.6rem;
    font-family: monospace;
    font-size: 0.85rem;
  }
  .path-input:focus { outline: none; border-color: #4a9eff; }

  .btn {
    background: #1e1e1e;
    border: 1px solid #333;
    color: #aaa;
    border-radius: 4px;
    padding: 0.4rem 0.9rem;
    font-size: 0.85rem;
    cursor: pointer;
  }
  .btn:hover:not(:disabled) { color: #fff; border-color: #555; }
  .btn:disabled { opacity: 0.4; cursor: default; }
  .btn.primary { border-color: #4a9eff; color: #4a9eff; }
  .btn.primary:hover:not(:disabled) { background: #162033; }

  .error {
    padding: 0.5rem 1rem;
    color: #e55;
    font-size: 0.85rem;
    background: #1a0d0d;
    border-bottom: 1px solid #3a1515;
  }

  .waveform-wrap {
    padding: 0.75rem 1rem;
    border-bottom: 1px solid #222;
  }

  .no-media {
    padding: 1rem;
    color: #555;
    font-style: italic;
    font-size: 0.85rem;
  }

  .main {
    display: flex;
    flex: 1;
    min-height: 0;
    overflow: hidden;
    border-bottom: 1px solid #222;
  }

  .left {
    width: 280px;
    flex-shrink: 0;
    border-right: 1px solid #222;
    padding: 0.75rem;
    overflow: hidden;
    display: flex;
    flex-direction: column;
  }

  .right {
    flex: 1;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  .edit-section {
    flex: 1;
    padding: 0.75rem;
    display: flex;
    flex-direction: column;
    border-bottom: 1px solid #1e1e1e;
    min-height: 0;
  }

  .edit-area {
    flex: 1;
    resize: none;
    background: #0d0d0d;
    border: 1px solid #2a2a2a;
    border-radius: 4px;
    color: #ccc;
    font-family: monospace;
    font-size: 0.85rem;
    line-height: 1.6;
    padding: 0.5rem 0.6rem;
    min-height: 200px;
  }
  .edit-area:focus { outline: none; border-color: #333; }

  .diff-section {
    flex: 0 0 auto;
    max-height: 220px;
    overflow-y: auto;
    padding: 0.75rem;
    background: #0e0e0e;
  }

  .hint { font-weight: 400; color: #444; text-transform: none; letter-spacing: 0; font-size: 0.75rem; }

  .footer {
    padding: 0.75rem 1rem;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    background: #161616;
  }

  .footer > :global(div), .footer > button, .footer > label {
    /* keep buttons on one row */
  }

  .footer > button, .footer > label {
    align-self: flex-start;
  }

  .padding-label {
    font-size: 0.8rem;
    color: #666;
    display: flex;
    align-items: center;
    gap: 0.4rem;
  }

  .padding-input {
    width: 60px;
    background: #0e0e0e;
    border: 1px solid #333;
    border-radius: 3px;
    color: #aaa;
    padding: 0.2rem 0.4rem;
    font-size: 0.8rem;
  }

  .progress {
    font-family: monospace;
    font-size: 0.78rem;
    color: #888;
    background: #0a0a0a;
    border-radius: 4px;
    padding: 0.5rem 0.75rem;
    line-height: 1.6;
  }

  .output {
    font-size: 0.82rem;
    color: #888;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }
  .output strong { color: #aaa; }

  /* footer action row */
  .footer {
    flex-direction: row;
    flex-wrap: wrap;
    align-items: flex-start;
    gap: 0.5rem;
  }
  .progress, .output {
    flex-basis: 100%;
  }
</style>
