<script setup lang="ts">
import { onMounted, onUnmounted, nextTick, ref, watch } from 'vue'
import { useChatStore } from '@/stores/chat'
import ChatMessage from '@/components/knowledge/ChatMessage.vue'
import ChatInput from '@/components/knowledge/ChatInput.vue'
import ExampleChips from '@/components/knowledge/ExampleChips.vue'
import { ChatDotRound, Plus } from '@element-plus/icons-vue'

const chat = useChatStore()
const listRef = ref<HTMLElement | null>(null)

onMounted(() => {
  chat.loadExamples()
  window.addEventListener('beforeunload', onUnload)
})

onUnmounted(() => {
  window.removeEventListener('beforeunload', onUnload)
})

function onUnload() {
  chat.saveOnUnload()
}

watch(
  () => chat.messages.length,
  async () => {
    await nextTick()
    if (listRef.value) listRef.value.scrollTop = listRef.value.scrollHeight
  },
)

watch(
  () => chat.messages[chat.messages.length - 1]?.content,
  async () => {
    await nextTick()
    if (listRef.value) listRef.value.scrollTop = listRef.value.scrollHeight
  },
)

async function onNewChat() {
  await chat.newChat()
}

function onSelectExample(text: string) {
  chat.send(text)
}
</script>

<template>
  <main class="enterprise-page chat-workspace">
    <header class="page-header" data-test="page-header">
      <div class="page-header__copy">
        <h1>智能问答</h1>
        <p>基于企业知识库检索法规、合同与制度文档</p>
      </div>
      <div class="page-header__actions">
        <el-tag :type="chat.hasWeb ? 'primary' : 'info'" effect="plain">
          {{ chat.hasWeb ? '含网络补充' : '本地知识库' }}
        </el-tag>
        <el-button
          data-test="new-chat"
          :icon="Plus"
          :disabled="chat.responding"
          @click="onNewChat"
        >
          新建对话
        </el-button>
      </div>
    </header>

    <div class="chat-layout">
      <section class="surface-panel chat-panel" aria-label="问答会话">
        <div class="surface-panel__header chat-panel__header">
          <div>
            <h2>当前会话</h2>
            <p>{{ chat.responding ? '正在生成回答' : '等待提问' }}</p>
          </div>
          <span class="live-status" :class="{ 'live-status--active': chat.responding }">
            <span aria-hidden="true" />{{ chat.responding ? '处理中' : '就绪' }}
          </span>
        </div>

        <div ref="listRef" class="chat-messages" aria-live="polite">
          <div v-if="!chat.messages.length" class="msg-empty">
            <el-icon aria-hidden="true"><ChatDotRound /></el-icon>
            <strong>开始新的知识问答</strong>
            <span>输入问题，或从推荐问题中选择</span>
          </div>
          <ChatMessage
            v-for="(m, i) in chat.messages"
            :key="i"
            :role="m.role"
            :content="m.content"
          />
        </div>

        <div class="chat-composer">
          <ChatInput
            v-model="chat.input"
            :responding="chat.responding"
            @send="chat.send()"
            @stop="chat.stop()"
          />
        </div>
      </section>

      <aside class="surface-panel chat-context" aria-label="推荐问题">
        <div class="surface-panel__header">
          <div>
            <h2>常用入口</h2>
            <p>从高频问题快速开始</p>
          </div>
        </div>
        <div class="chat-context__body">
          <ExampleChips
            :examples="chat.examples"
            :disabled="chat.responding"
            @select="onSelectExample"
          />
          <el-empty v-if="!chat.examples.length" :image-size="56" description="暂无推荐问题" />
        </div>
      </aside>
    </div>
  </main>
</template>
