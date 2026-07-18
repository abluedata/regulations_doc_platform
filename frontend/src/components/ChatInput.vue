<script setup lang="ts">
const model = defineModel<string>({ default: '' })
const props = defineProps<{
  responding?: boolean
  disabled?: boolean
}>()
const emit = defineEmits<{
  send: []
  stop: []
}>()

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    if (!props.responding) emit('send')
  }
}
</script>

<template>
  <div class="chat-input-row">
    <el-input
      v-model="model"
      type="textarea"
      :autosize="{ minRows: 2, maxRows: 6 }"
      :placeholder="responding ? '正在回答中…' : '输入你的问题'"
      :disabled="!!disabled || !!responding"
      @keydown="onKeydown"
    />
    <el-button
      v-if="!responding"
      type="primary"
      circle
      :disabled="!model.trim()"
      @click="emit('send')"
    >
      ↑
    </el-button>
    <el-button v-else type="danger" circle @click="emit('stop')">■</el-button>
  </div>
</template>
