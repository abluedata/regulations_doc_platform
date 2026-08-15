<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { ChatDotRound, Delete, Promotion } from '@element-plus/icons-vue'
import type { ReviewRisk } from '@/types'
import { useReviewStore } from '@/stores/review'
import { getActivePinia } from 'pinia'
import { createConversation, streamReviewAssistant } from '@/api/review'
import type { ReviewCitation } from '@/api/review'

type AssistantRole = 'user' | 'assistant'

interface AssistantMessage {
  id: number
  role: AssistantRole
  content: string
  citations?: ReviewCitation[]
  refused?: boolean
  error?: boolean
  status?: string
}

const props = defineProps<{
  risk?: ReviewRisk
}>()
const emit = defineEmits<{ locate: [anchor: ReviewCitation] }>()
const store = getActivePinia() ? useReviewStore() : null

const input = ref('')
const nextMessageId = ref(2)
const messageList = ref<HTMLElement | null>(null)
const conversationByDocument = new Map<string, string>()
const isStreaming = ref(false)
const selectedMembershipId = ref(store?.files.find((file) => file.status === 'ready')?.id ?? '')
const messages = ref<AssistantMessage[]>([
  {
    id: 1,
    role: 'assistant',
    content: '请选择当前任务中的一份文档。回答只依据该文档原文，并提供可定位引用。',
  },
])

const suggestions = ['为什么被判定为风险？', '建议如何修改？', '与标准模板有什么差异？']
const contextLabel = computed(() =>
  selectedDocument.value ? `当前文档 · ${selectedDocument.value.name}` : '尚未选择可问答文档',
)
const readyDocuments = computed(() => store?.files.filter((file) => file.status === 'ready') ?? [])
const selectedDocument = computed(() => readyDocuments.value.find((file) => file.id === selectedMembershipId.value))

async function sendQuestion(question = input.value) {
  const normalized = question.trim()
  if (!normalized) return

  messages.value.push({ id: nextMessageId.value++, role: 'user', content: normalized })
  const answer: AssistantMessage = { id: nextMessageId.value++, role: 'assistant', content: '' }
  messages.value.push(answer)
  input.value = ''
  if (!store?.analysisJobId || !selectedDocument.value) {
    answer.content = '请先选择当前审查任务中已就绪的文档。'
    answer.error = true
  } else {
    isStreaming.value = true
    try {
      let conversationId = conversationByDocument.get(selectedDocument.value.id)
      if (!conversationId) {
        conversationId = (await createConversation(store.analysisJobId, selectedDocument.value.id)).data.id
        conversationByDocument.set(selectedDocument.value.id, conversationId)
      }
      await streamReviewAssistant(conversationId, {
        request_id: crypto.randomUUID(), message: normalized, finding_id: props.risk?.id,
        history: messages.value.slice(0, -2).map(({ role, content }) => ({ role, content })),
      }, {
        onStatus: (data) => { answer.status = data.type === 'retrieving' ? '正在检索当前文档' : '正在组织回答' },
        onToken: (data) => { answer.status = ''; answer.content += String(data.content ?? '') },
        onDone: (data) => {
          answer.status = ''
          answer.refused = data.refused
          answer.citations = Array.isArray(data.citations) ? data.citations.filter(Boolean) : []
          if (!answer.content) answer.content = data.answer
        },
        onError: (data) => { answer.status = ''; answer.error = true; answer.content = data.message || '审查问答服务暂时不可用。' },
      })
      if (!answer.content) answer.content = '当前审查任务没有可引用的证据，无法回答该问题。'
    } catch {
      answer.content = '审查问答服务暂时不可用，请稍后重试。'
    } finally { isStreaming.value = false }
  }
  await nextTick()
  if (messageList.value) messageList.value.scrollTop = messageList.value.scrollHeight
}

function clearMessages() {
  messages.value = [
    {
      id: nextMessageId.value++,
      role: 'assistant',
      content: '对话已清空。请选择推荐问题，或输入你想了解的条款问题。',
    },
  ]
}
</script>

<template>
  <section class="review-assistant" aria-labelledby="review-assistant-title">
    <header class="assistant-header">
      <div class="assistant-heading-copy">
        <span class="assistant-title-row">
          <el-icon aria-hidden="true"><ChatDotRound /></el-icon>
          <strong id="review-assistant-title">条款问答助手</strong>
        </span>
        <span data-test="assistant-context" class="assistant-context">{{ contextLabel }}</span>
        <select v-model="selectedMembershipId" data-test="assistant-document" aria-label="选择问答文档" :disabled="isStreaming || readyDocuments.length < 2">
          <option value="" disabled>选择文档</option>
          <option v-for="document in readyDocuments" :key="document.id" :value="document.id">{{ document.name }}</option>
        </select>
      </div>
      <el-tooltip content="清空对话" placement="left">
        <button type="button" class="assistant-clear" aria-label="清空问答记录" @click="clearMessages">
          <el-icon><Delete /></el-icon>
        </button>
      </el-tooltip>
    </header>

    <div ref="messageList" class="assistant-messages" aria-live="polite">
      <div
        v-for="message in messages"
        :key="message.id"
        class="assistant-message"
        :class="`assistant-message--${message.role}`"
        :data-role="message.role"
      >
        <span class="assistant-message__label">{{ message.role === 'assistant' ? '助手' : '你' }}</span>
        <p :data-test="message.refused ? 'assistant-refusal' : undefined" :class="{ 'assistant-message__refusal': message.refused, 'assistant-message__error': message.error }">
          <span v-if="message.status" class="assistant-status">{{ message.status }}</span>{{ message.content }}<span v-if="isStreaming && message === messages.at(-1)" class="sr-only">正在生成回答</span>
        </p>
        <div v-if="message.citations?.length" class="assistant-citations" aria-label="回答引用">
          <button v-for="citation in message.citations" :key="citation.citation_id" data-test="assistant-citation" type="button" @click="emit('locate', citation)">
            <span>{{ citation.filename }}{{ citation.locator.page_number ? ` · 第 ${citation.locator.page_number} 页` : '' }}</span>
            <q>{{ citation.quote }}</q>
          </button>
        </div>
      </div>
    </div>

    <div class="assistant-suggestions" aria-label="推荐问题">
      <button v-for="suggestion in suggestions" :key="suggestion" type="button" @click="sendQuestion(suggestion)">
        {{ suggestion }}
      </button>
    </div>

    <form class="assistant-composer" @submit.prevent="sendQuestion()">
      <label for="review-assistant-input">继续追问</label>
      <div class="assistant-input-row">
        <textarea
          id="review-assistant-input"
          v-model="input"
          data-test="assistant-input"
          rows="2"
          placeholder="询问当前条款的风险或修改建议"
          @keydown.enter.exact.prevent="sendQuestion()"
        />
        <el-tooltip content="发送问题" placement="top">
          <button
            data-test="assistant-send"
            type="button"
          :disabled="!input.trim() || isStreaming || !selectedDocument"
            aria-label="发送问题"
            @click="sendQuestion()"
          >
            <el-icon><Promotion /></el-icon>
          </button>
        </el-tooltip>
      </div>
    </form>

    <p class="assistant-disclaimer">回答基于当前审查证据，不构成法律意见。</p>
  </section>
</template>

<style scoped>
.review-assistant {
  display: flex;
  min-height: 0;
  flex: 1;
  flex-direction: column;
  background: var(--surface);
}

.assistant-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 18px 20px;
  border-bottom: 1px solid var(--outline-soft);
  background: var(--surface-low);
}

.assistant-heading-copy { min-width: 0; flex: 1; }
.assistant-title-row {
  display: flex;
  align-items: center;
  gap: 7px;
  color: var(--ink);
  font-size: 14px;
}

.assistant-title-row .el-icon {
  color: var(--action);
  font-size: 18px;
}

.assistant-context {
  display: block;
  margin-top: 6px;
  color: var(--ink-muted);
  font-size: 11px;
}

.assistant-heading-copy select {
  width: 100%;
  min-height: 36px;
  margin-top: 10px;
  padding: 0 9px;
  border: 1px solid var(--outline);
  border-radius: var(--radius-sm);
  color: var(--ink);
  background: var(--surface);
}

.assistant-clear {
  display: grid;
  width: var(--control-height);
  height: var(--control-height);
  flex: 0 0 var(--control-height);
  place-items: center;
  padding: 0;
  border: 0;
  border-radius: var(--radius-sm);
  color: var(--ink-muted);
  background: transparent;
  cursor: pointer;
}

.assistant-clear:hover {
  color: var(--danger);
  background: var(--surface-high);
}

.assistant-messages {
  display: flex;
  min-height: 240px;
  max-height: 380px;
  flex: 1;
  flex-direction: column;
  gap: 12px;
  overflow-y: auto;
  padding: 18px 20px;
}

.assistant-message {
  display: flex;
  max-width: 92%;
  flex-direction: column;
  gap: 4px;
}

.assistant-message--user {
  align-self: flex-end;
  align-items: flex-end;
}

.assistant-message__label {
  color: var(--ink-muted);
  font-size: 10px;
  font-weight: 700;
}

.assistant-message p {
  margin: 0;
  padding: 10px 12px;
  border-radius: var(--radius-md);
  color: var(--ink);
  background: var(--surface-low);
  font-size: 12px;
  line-height: 1.65;
}

.assistant-message--user p {
  color: #ffffff;
  background: var(--action);
}

.assistant-suggestions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 0 20px 14px;
}

.assistant-suggestions button {
  min-height: 44px;
  padding: 6px 10px;
  border: 1px solid var(--outline-soft);
  border-radius: var(--radius-sm);
  color: var(--action);
  background: var(--surface);
  font-size: 11px;
  cursor: pointer;
}

.assistant-suggestions button:hover {
  border-color: var(--action);
  background: var(--action-soft);
}

.assistant-composer {
  display: grid;
  gap: 7px;
  padding: 14px 20px;
  border-top: 1px solid var(--outline-soft);
}

.assistant-composer > label {
  color: var(--ink-muted);
  font-size: 10px;
  font-weight: 700;
}

.assistant-input-row {
  display: flex;
  align-items: flex-end;
  gap: 8px;
}

.assistant-input-row textarea {
  min-width: 0;
  flex: 1;
  resize: none;
  padding: 9px 10px;
  border: 1px solid var(--outline);
  border-radius: var(--radius-sm);
  color: var(--ink);
  background: var(--surface);
  font: inherit;
  font-size: 12px;
  line-height: 1.5;
}

.assistant-input-row textarea:focus-visible {
  border-color: var(--action);
  outline: 2px solid var(--action-soft);
}

.assistant-input-row button {
  display: grid;
  width: 44px;
  height: 44px;
  flex: 0 0 44px;
  place-items: center;
  padding: 0;
  border: 0;
  border-radius: var(--radius-sm);
  color: #ffffff;
  background: var(--action);
  cursor: pointer;
}

.assistant-status { display: block; color: var(--ink-muted); }
.assistant-message__refusal { border: 1px solid var(--warning-outline); background: #fff8ed !important; }
.assistant-message__error { border: 1px solid var(--danger-outline); background: var(--danger-soft) !important; }
.assistant-citations { display: flex; flex-direction: column; gap: 6px; }
.assistant-citations button { display: flex; min-height: 44px; flex-direction: column; gap: 3px; padding: 8px 10px; border: 1px solid var(--outline); border-radius: var(--radius-sm); color: var(--action); background: var(--surface); text-align: left; cursor: pointer; }
.assistant-citations q { max-width: 42ch; color: var(--ink-muted); font-size: 11px; overflow-wrap: anywhere; }

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { scroll-behavior: auto !important; transition-duration: 0.01ms !important; animation-duration: 0.01ms !important; }
}

.assistant-input-row button:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

.assistant-disclaimer {
  margin: 0;
  padding: 0 20px 16px;
  color: var(--ink-muted);
  font-size: 10px;
}

@media (max-width: 680px) {
  .assistant-messages {
    max-height: 320px;
  }
}
</style>
