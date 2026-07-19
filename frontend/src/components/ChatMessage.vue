<script setup lang="ts">
import { computed } from 'vue'
import { marked } from 'marked'
import { Cpu, UserFilled } from '@element-plus/icons-vue'

const props = defineProps<{
  role: 'user' | 'assistant'
  content: string
}>()

marked.setOptions({ breaks: true, gfm: true })

const html = computed(() => {
  if (props.role === 'user') {
    return escapeHtml(props.content)
  }
  return marked.parse(props.content || '') as string
})

function escapeHtml(s: string) {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/\n/g, '<br/>')
}
</script>

<template>
  <article class="msg" :class="role" :aria-label="role === 'user' ? '用户消息' : '智能助手消息'">
    <div class="msg-avatar" aria-hidden="true">
      <el-icon><UserFilled v-if="role === 'user'" /><Cpu v-else /></el-icon>
    </div>
    <div class="msg-content" v-html="html" />
  </article>
</template>
