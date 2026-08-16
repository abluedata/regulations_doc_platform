<script setup lang="ts">
import { Promotion, VideoPause } from '@element-plus/icons-vue'

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
      :autosize="{ minRows: 3, maxRows: 3 }"
      :placeholder="responding ? '正在回答中…' : '输入你的问题'"
      :disabled="!!disabled || !!responding"
      aria-label="问题内容"
      @keydown="onKeydown"
    />
    <el-tooltip v-if="!responding" content="发送问题" placement="top">
      <el-button
        type="primary"
        circle
        aria-label="发送问题"
        :icon="Promotion"
        :disabled="!model.trim()"
        @click="emit('send')"
      />
    </el-tooltip>
    <el-tooltip v-else content="停止回答" placement="top">
      <el-button
        type="danger"
        circle
        aria-label="停止回答"
        :icon="VideoPause"
        @click="emit('stop')"
      />
    </el-tooltip>
  </div>
</template>
