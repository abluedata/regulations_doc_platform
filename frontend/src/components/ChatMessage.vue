<script setup lang="ts">
import { Cpu, UserFilled } from '@element-plus/icons-vue'
import SafeMarkdown from '@/components/SafeMarkdown.vue'

const props = defineProps<{
  role: 'user' | 'assistant'
  content: string
}>()

</script>

<template>
  <article class="msg" :class="role" :aria-label="role === 'user' ? '用户消息' : '智能助手消息'">
    <div class="msg-avatar" aria-hidden="true">
      <el-icon><UserFilled v-if="role === 'user'" /><Cpu v-else /></el-icon>
    </div>
    <div v-if="role === 'user'" class="msg-content user-text">{{ content }}</div>
    <SafeMarkdown v-else class="msg-content" :content="content" />
  </article>
</template>
