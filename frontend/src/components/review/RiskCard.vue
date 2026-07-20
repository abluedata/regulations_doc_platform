<script setup lang="ts">
import { Check, Close, Warning } from '@element-plus/icons-vue'
import { computed } from 'vue'
import type { ReviewRisk } from '@/types'

export type RiskAction = 'pending' | 'accepted' | 'dismissed'

const props = withDefaults(
  defineProps<{
    risk: ReviewRisk
    action?: RiskAction
  }>(),
  {
    action: 'pending',
  },
)

defineEmits<{
  select: [id: string]
}>()

const levelLabel = {
  high: '高风险',
  medium: '中风险',
  low: '低风险',
} as const

const actionLabel = computed(() => {
  if (props.action === 'accepted') return '已采纳建议'
  if (props.action === 'dismissed') return '已忽略风险'
  return ''
})
</script>

<template>
  <button
    class="risk-card"
    :class="[`risk-card--${risk.level}`, { 'risk-card--resolved': action !== 'pending' }]"
    type="button"
    :data-risk-id="risk.id"
    :data-action="action"
    @click="$emit('select', risk.id)"
  >
    <span class="risk-card__heading">
      <span class="risk-card__level">
        <el-icon aria-hidden="true"><Warning /></el-icon>
        {{ levelLabel[risk.level] }}
      </span>
      <span class="risk-card__section">{{ risk.section }}</span>
    </span>

    <strong class="risk-card__title">{{ risk.title }}</strong>
    <span class="risk-card__description">{{ risk.description }}</span>

    <span v-if="risk.currentText || risk.referenceText" class="risk-card__comparison">
      <span v-if="risk.currentText">
        <b>当前条款</b>
        <span>{{ risk.currentText }}</span>
      </span>
      <span v-if="risk.referenceText" class="risk-card__reference">
        <b>标准模板匹配</b>
        <span>{{ risk.referenceText }}</span>
      </span>
    </span>

    <span v-if="actionLabel" class="risk-card__action">
      <el-icon aria-hidden="true">
        <Check v-if="action === 'accepted'" />
        <Close v-else />
      </el-icon>
      {{ actionLabel }}
    </span>
  </button>
</template>

<style scoped>
.risk-card {
  display: flex;
  width: 100%;
  flex-direction: column;
  gap: 8px;
  padding: 16px;
  border: 1px solid var(--outline-soft);
  border-radius: var(--radius-md);
  color: var(--ink);
  background: var(--surface);
  text-align: left;
  cursor: pointer;
  transition:
    background-color 160ms ease-out,
    box-shadow 160ms ease-out;
}

.risk-card:hover {
  background: var(--surface-low);
  box-shadow: var(--shadow-sm);
}

.risk-card--high {
  border-color: var(--danger-outline);
}

.risk-card--medium {
  border-color: var(--warning-outline);
}

.risk-card--low {
  border-color: var(--action-outline);
}

.risk-card--resolved {
  opacity: 0.72;
}

.risk-card__heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.risk-card__level {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 6px;
  border-radius: var(--radius-sm);
  color: #ffffff;
  background: var(--action);
  font-size: 10px;
  font-weight: 700;
}

.risk-card--high .risk-card__level {
  background: var(--danger);
}

.risk-card--medium .risk-card__level {
  background: var(--warning);
}

.risk-card__section {
  color: var(--ink-muted);
  font-size: 11px;
  font-weight: 600;
}

.risk-card__title {
  font-size: 14px;
}

.risk-card__description {
  color: var(--ink-muted);
  font-size: 12px;
  line-height: 1.6;
}

.risk-card__comparison {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 4px;
  padding-top: 12px;
  border-top: 1px solid var(--outline-soft);
}

.risk-card__comparison > span {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 9px;
  border-radius: var(--radius-sm);
  color: var(--ink-muted);
  background: var(--surface-low);
  font-size: 11px;
}

.risk-card__comparison b {
  color: var(--ink);
  font-size: 10px;
}

.risk-card__comparison .risk-card__reference {
  border: 1px solid var(--action-outline);
  background: var(--action-subtle);
}

.risk-card__reference b {
  color: var(--action);
}

.risk-card__action {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  margin-top: 4px;
  color: var(--success);
  font-size: 11px;
  font-weight: 700;
}

.risk-card[data-action="dismissed"] .risk-card__action {
  color: var(--ink-muted);
}
</style>
