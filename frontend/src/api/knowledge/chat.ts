import http from '../http'
import type { ChatMessage } from '@/types'

export function fetchExamples() {
  return http.get<{ examples: string[] }>('/chat/examples')
}

export function saveSession(payload: {
  messages: ChatMessage[]
  route?: string
  has_web?: boolean
}) {
  return http.post<{ id: string }>('/chat/sessions', payload)
}

export function stopChat(requestId: string) {
  return http.post('/chat/stop', { request_id: requestId })
}

export type StreamHandlers = {
  onMeta?: (data: { request_id: string }) => void
  onStatus?: (data: { type: string }) => void
  onToken?: (data: { content: string }) => void
  onDone?: (data: { route: string; has_web: boolean }) => void
  onError?: (data: { message: string }) => void
}

/**
 * POST SSE 流式问答（fetch + ReadableStream）
 */
export async function streamChat(
  payload: {
    message: string
    history: ChatMessage[]
    request_id?: string
  },
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const base = import.meta.env.VITE_API_BASE || '/api'
  const res = await fetch(`${base}/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify(payload),
    signal,
  })

  if (!res.ok || !res.body) {
    let detail = `HTTP ${res.status}`
    try {
      const j = await res.json()
      if (j?.detail) detail = j.detail
    } catch {
      /* ignore */
    }
    throw new Error(detail)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    // 按 SSE 事件块分割（空行）
    const parts = buffer.split('\n\n')
    buffer = parts.pop() || ''

    for (const block of parts) {
      if (!block.trim()) continue
      let event = 'message'
      const dataLines: string[] = []
      for (const line of block.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim()
        else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim())
      }
      if (!dataLines.length) continue
      let data: any
      try {
        data = JSON.parse(dataLines.join('\n'))
      } catch {
        data = { content: dataLines.join('\n') }
      }

      if (event === 'meta') handlers.onMeta?.(data)
      else if (event === 'status') handlers.onStatus?.(data)
      else if (event === 'token') handlers.onToken?.(data)
      else if (event === 'done') handlers.onDone?.(data)
      else if (event === 'error') handlers.onError?.(data)
    }
  }
}
