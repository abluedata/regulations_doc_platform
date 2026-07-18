<script setup lang="ts">
import { onMounted, onUnmounted, nextTick, ref, watch } from 'vue'
import { useChatStore } from '@/stores/chat'
import ChatMessage from '@/components/ChatMessage.vue'
import ChatInput from '@/components/ChatInput.vue'
import ExampleChips from '@/components/ExampleChips.vue'

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
  <div class="page-card chat-panel">
    <div class="chat-toolbar">
      <el-button size="small" :disabled="chat.responding" @click="onNewChat">
        + 新建对话
      </el-button>
    </div>

    <div ref="listRef" class="chat-messages">
      <div v-if="!chat.messages.length" class="msg-empty">
        输入问题开始问答，或点击下方推荐问题
      </div>
      <ChatMessage
        v-for="(m, i) in chat.messages"
        :key="i"
        :role="m.role"
        :content="m.content"
      />
    </div>

    <ChatInput
      v-model="chat.input"
      :responding="chat.responding"
      @send="chat.send()"
      @stop="chat.stop()"
    />

    <ExampleChips
      :examples="chat.examples"
      :disabled="chat.responding"
      @select="onSelectExample"
    />
  </div>
</template>
