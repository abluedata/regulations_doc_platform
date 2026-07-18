import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { ChatMessage } from '@/types'
import { fetchExamples, saveSession, stopChat, streamChat } from '@/api/chat'

export const useChatStore = defineStore('chat', () => {
  const messages = ref<ChatMessage[]>([])
  const examples = ref<string[]>([])
  const responding = ref(false)
  const requestId = ref<string | null>(null)
  const route = ref('local')
  const hasWeb = ref(false)
  const input = ref('')
  let abortController: AbortController | null = null

  async function loadExamples() {
    try {
      const { data } = await fetchExamples()
      examples.value = data.examples || []
    } catch {
      examples.value = []
    }
  }

  async function send(text?: string) {
    const q = (text ?? input.value).trim()
    if (!q || responding.value) return

    input.value = ''
    messages.value.push({ role: 'user', content: q })
    messages.value.push({ role: 'assistant', content: '' })
    responding.value = true
    requestId.value = crypto.randomUUID()
    abortController = new AbortController()

    const history = messages.value.slice(0, -2)

    try {
      await streamChat(
        {
          message: q,
          history,
          request_id: requestId.value,
        },
        {
          onMeta: (d) => {
            if (d.request_id) requestId.value = d.request_id
          },
          onStatus: (d) => {
            const last = messages.value[messages.value.length - 1]
            if (last?.role === 'assistant') {
              last.content =
                d.type === 'parallel'
                  ? '🔍 检测到复杂问题，启动并行搜索...'
                  : '🔍 正在搜索...'
            }
          },
          onToken: (d) => {
            const last = messages.value[messages.value.length - 1]
            if (!last || last.role !== 'assistant') return
            // 首个正式 token 替换状态行
            if (last.content.startsWith('🔍')) {
              last.content = d.content || ''
            } else {
              last.content += d.content || ''
            }
          },
          onDone: (d) => {
            route.value = d.route || 'local'
            hasWeb.value = !!d.has_web
          },
          onError: (d) => {
            const last = messages.value[messages.value.length - 1]
            if (last?.role === 'assistant') {
              last.content = `❌ ${d.message || '请求失败'}`
            }
          },
        },
        abortController.signal,
      )
    } catch (e: any) {
      if (e?.name !== 'AbortError') {
        const last = messages.value[messages.value.length - 1]
        if (last?.role === 'assistant') {
          last.content = last.content?.startsWith('🔍')
            ? `❌ ${e.message || '请求失败'}`
            : last.content || `❌ ${e.message || '请求失败'}`
        }
      }
    } finally {
      responding.value = false
      requestId.value = null
      abortController = null
    }
  }

  async function stop() {
    if (requestId.value) {
      try {
        await stopChat(requestId.value)
      } catch {
        /* ignore */
      }
    }
    abortController?.abort()
    responding.value = false
  }

  async function newChat() {
    if (responding.value) return
    if (messages.value.length >= 2) {
      try {
        await saveSession({
          messages: messages.value,
          route: route.value,
          has_web: hasWeb.value,
        })
      } catch {
        /* 保存失败仍清空本地 */
      }
    }
    messages.value = []
    route.value = 'local'
    hasWeb.value = false
  }

  /** 页面关闭时尽量保存 */
  function saveOnUnload() {
    if (messages.value.length < 2) return
    const payload = JSON.stringify({
      messages: messages.value,
      route: route.value,
      has_web: hasWeb.value,
    })
    const base = import.meta.env.VITE_API_BASE || '/api'
    const url = `${base}/chat/sessions`
    if (navigator.sendBeacon) {
      const blob = new Blob([payload], { type: 'application/json' })
      navigator.sendBeacon(url, blob)
    }
  }

  return {
    messages,
    examples,
    responding,
    requestId,
    route,
    hasWeb,
    input,
    loadExamples,
    send,
    stop,
    newChat,
    saveOnUnload,
  }
})
