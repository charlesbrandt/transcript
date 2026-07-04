const BASE = '/api'

export interface Segment {
  start: number
  end: number
  text: string
}

export interface SessionResponse {
  metadata_path: string
  edit_path: string
  edit_text: string
  segments: Segment[]
  media_path: string | null
}

export interface AlignedWord {
  word: string
  start: number
  end: number
  status: 'KEEP' | 'REMOVE'
}

export interface DiffResponse {
  aligned_words: AlignedWord[]
  kept_count: number
  removed_count: number
  time_saved: number
  time_saved_pct: number
}

export type SseEvent =
  | { type: 'progress'; message: string }
  | { type: 'done'; output_path?: string; metadata_path?: string }
  | { type: 'error'; message: string }

export async function loadSession(metadataPath: string): Promise<SessionResponse> {
  const r = await fetch(`${BASE}/session?metadata=${encodeURIComponent(metadataPath)}`)
  if (!r.ok) {
    const body = await r.json().catch(() => ({}))
    throw new Error((body as { detail?: string }).detail ?? `HTTP ${r.status}`)
  }
  return r.json()
}

export async function fetchDiff(metadataPath: string, editText: string): Promise<DiffResponse> {
  const r = await fetch(`${BASE}/diff`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ metadata_path: metadataPath, edit_text: editText }),
  })
  if (!r.ok) {
    const body = await r.json().catch(() => ({}))
    throw new Error((body as { detail?: string }).detail ?? `HTTP ${r.status}`)
  }
  return r.json()
}

export function streamRender(
  metadataPath: string,
  editText: string,
  padding: number,
  onEvent: (e: SseEvent) => void
): () => void {
  let aborted = false
  fetch(`${BASE}/render`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ metadata_path: metadataPath, edit_text: editText, padding }),
  }).then(async r => {
    if (!r.ok || !r.body) {
      const body = await r.json().catch(() => ({}))
      onEvent({ type: 'error', message: (body as { detail?: string }).detail ?? `HTTP ${r.status}` })
      return
    }
    const reader = r.body.getReader()
    const dec = new TextDecoder()
    let buf = ''
    while (!aborted) {
      const { done, value } = await reader.read()
      if (done) break
      buf += dec.decode(value, { stream: true })
      const lines = buf.split('\n')
      buf = lines.pop() ?? ''
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try { onEvent(JSON.parse(line.slice(6))) } catch (_) {}
        }
      }
    }
  })
  return () => { aborted = true }
}

export function streamRetranscribe(
  metadataPath: string,
  onEvent: (e: SseEvent) => void
): () => void {
  let aborted = false
  fetch(`${BASE}/retranscribe`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ metadata_path: metadataPath }),
  }).then(async r => {
    if (!r.ok || !r.body) {
      const body = await r.json().catch(() => ({}))
      onEvent({ type: 'error', message: (body as { detail?: string }).detail ?? `HTTP ${r.status}` })
      return
    }
    const reader = r.body.getReader()
    const dec = new TextDecoder()
    let buf = ''
    while (!aborted) {
      const { done, value } = await reader.read()
      if (done) break
      buf += dec.decode(value, { stream: true })
      const lines = buf.split('\n')
      buf = lines.pop() ?? ''
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try { onEvent(JSON.parse(line.slice(6))) } catch (_) {}
        }
      }
    }
  })
  return () => { aborted = true }
}

export function mediaUrl(path: string): string {
  return `${BASE}/media?path=${encodeURIComponent(path)}`
}
