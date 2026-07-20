<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { ChatDotRound, Delete, Promotion } from '@element-plus/icons-vue'
import type { ReviewRisk } from '@/types'

type AssistantRole = 'user' | 'assistant'

interface AssistantMessage {
  id: number
  role: AssistantRole
  content: string
}

const props = defineProps<{
  risk?: ReviewRisk
}>()

const input = ref('')
const nextMessageId = ref(2)
const messageList = ref<HTMLElement | null>(null)
const messages = ref<AssistantMessage[]>([
  {
    id: 1,
    role: 'assistant',
    content: '我可以结合当前风险解释条款、比较标准模板，并给出修改方向。',
  },
])

const suggestions = ['为什么被判定为风险？', '建议如何修改？', '与标准模板有什么差异？']
const contextLabel = computed(() =>
  props.risk ? `${props.risk.section} · ${props.risk.title}` : '尚未选择风险条款',
)

function buildAnswer(question: string) {
  const risk = props.risk
  if (!risk) return '请先在“审查发现”中选择一项风险，我会以该条款作为回答上下文。'

  if (question.includes('修改') || question.includes('建议')) {
    return `${risk.title}建议采用明确、可量化的限制。${risk.referenceText ? `可参考：${risk.referenceText}` : '建议补充适用范围、金额或期限。'}`
  }
  if (question.includes('差异') || question.includes('模板')) {
    return `${risk.title}位于${risk.section}。当前文本与标准模板的主要差异是：${risk.currentText ?? risk.description}${risk.referenceText ? `；标准参考为：${risk.referenceText}` : '。'}`
  }
  return `${risk.title}被标记为${risk.level === 'high' ? '高' : risk.level === 'medium' ? '中' : '低'}风险，因为${risk.description}`
}

async function sendQuestion(question = input.value) {
  const normalized = question.trim()
  if (!normalized) return

  messages.value.push({ id: nextMessageId.value++, role: 'user', content: normalized })
  messages.value.push({ id: nextMessageId.value++, role: 'assistant', content: buildAnswer(normalized) })
  input.value = ''
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
      <div>
        <span class="assistant-title-row">
          <el-icon aria-hidden="true"><ChatDotRound /></el-icon>
          <strong id="review-assistant-title">条款问答助手</strong>
        </span>
        <span data-test="assistant-context" class="assistant-context">{{ contextLabel }}</span>
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
        <p>{{ message.content }}</p>
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
            :disabled="!input.trim()"
            aria-label="发送问题"
            @click="sendQuestion()"
          >
            <el-icon><Promotion /></el-icon>
          </button>
        </el-tooltip>
      </div>
    </form>

    <p class="assistant-disclaimer">回答仅用于界面演示，不构成法律意见。</p>
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
  min-height: var(--control-height);
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
  width: var(--control-height);
  height: var(--control-height);
  flex: 0 0 var(--control-height);
  place-items: center;
  padding: 0;
  border: 0;
  border-radius: var(--radius-sm);
  color: #ffffff;
  background: var(--action);
  cursor: pointer;
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
