<script setup lang="ts">
import { ArrowLeft, ArrowRight } from '@element-plus/icons-vue'

withDefaults(
  defineProps<{
    previousLabel?: string
    nextLabel?: string
    previousDisabled?: boolean
    nextDisabled?: boolean
  }>(),
  {
    previousLabel: '上一步',
    nextLabel: '下一步',
    previousDisabled: false,
    nextDisabled: false,
  },
)

defineEmits<{
  previous: []
  next: []
}>()
</script>

<template>
  <footer class="review-footer">
    <el-button
      data-test="review-previous"
      :disabled="previousDisabled"
      @click="$emit('previous')"
    >
      <el-icon aria-hidden="true"><ArrowLeft /></el-icon>
      {{ previousLabel }}
    </el-button>

    <div v-if="$slots.default" class="review-footer__message">
      <slot />
    </div>

    <el-button
      type="primary"
      data-test="review-next"
      :disabled="nextDisabled"
      @click="$emit('next')"
    >
      {{ nextLabel }}
      <el-icon aria-hidden="true"><ArrowRight /></el-icon>
    </el-button>
  </footer>
</template>

<style scoped>
.review-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-top: 32px;
  padding-top: 24px;
  border-top: 1px solid var(--outline-soft);
}

.review-footer__message {
  flex: 1;
  color: var(--ink-muted);
  font-size: 12px;
  font-style: italic;
  text-align: center;
}

@media (max-width: 600px) {
  .review-footer {
    align-items: stretch;
    flex-direction: column-reverse;
  }

  .review-footer :deep(.el-button) {
    width: 100%;
    margin-left: 0;
  }

  .review-footer__message {
    order: 1;
  }
}
</style>
