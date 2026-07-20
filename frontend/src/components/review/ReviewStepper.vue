<script setup lang="ts">
import { Check } from '@element-plus/icons-vue'

const props = defineProps<{
  current: number
}>()

const steps = ['文档上传', '范本选择', '条款设置', '智能审查'] as const

function stateFor(step: number) {
  if (step < props.current) return 'complete'
  if (step === props.current) return 'active'
  return 'upcoming'
}
</script>

<template>
  <ol class="review-stepper" aria-label="审查进度">
    <li
      v-for="(label, index) in steps"
      :key="label"
      class="review-stepper__item"
      :data-state="stateFor(index + 1)"
      :aria-current="stateFor(index + 1) === 'active' ? 'step' : undefined"
    >
      <span class="review-stepper__marker" aria-hidden="true">
        <el-icon v-if="stateFor(index + 1) === 'complete'"><Check /></el-icon>
        <span v-else>{{ index + 1 }}</span>
      </span>
      <span class="review-stepper__label">{{ index + 1 }}. {{ label }}</span>
    </li>
  </ol>
</template>

<style scoped>
.review-stepper {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0;
  margin: 0 0 32px;
  padding: 0;
  list-style: none;
}

.review-stepper__item {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--ink-muted);
  font-size: 12px;
  font-weight: 600;
}

.review-stepper__item:not(:last-child)::after {
  width: clamp(24px, 4vw, 56px);
  height: 1px;
  margin: 0 12px;
  background: var(--outline-soft);
  content: "";
}

.review-stepper__marker {
  display: grid;
  width: 32px;
  height: 32px;
  flex: 0 0 auto;
  place-items: center;
  border: 1px solid var(--outline);
  border-radius: 50%;
  background: var(--surface);
  font-weight: 700;
}

.review-stepper__item[data-state="complete"] {
  color: var(--action);
}

.review-stepper__item[data-state="complete"] .review-stepper__marker {
  border-color: var(--action);
  background: var(--action-soft);
}

.review-stepper__item[data-state="complete"]::after {
  background: var(--action);
}

.review-stepper__item[data-state="active"] {
  color: var(--ink);
}

.review-stepper__item[data-state="active"] .review-stepper__marker {
  border-color: var(--action);
  color: #ffffff;
  background: var(--action);
  box-shadow: 0 0 0 3px var(--action-soft);
}

.review-stepper__item[data-state="upcoming"] {
  color: #718196;
}

@media (max-width: 700px) {
  .review-stepper {
    justify-content: space-between;
    margin-bottom: 24px;
  }

  .review-stepper__item {
    flex: 1;
    justify-content: center;
  }

  .review-stepper__item:not(:last-child)::after {
    width: auto;
    flex: 1;
    margin: 0 6px;
  }

  .review-stepper__label {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip: rect(0 0 0 0);
    clip-path: inset(50%);
    white-space: nowrap;
  }
}
</style>
