<script setup lang="ts">
import { computed } from 'vue'
import { marked } from 'marked'

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
  <div class="msg" :class="role" v-html="html" />
</template>
