<script setup lang="ts">
import { Check, Close, Position, Warning } from '@element-plus/icons-vue'
import { computed } from 'vue'
import type { ReviewRisk } from '@/types'

export type RiskAction = 'pending' | 'accepted' | 'dismissed'

const props = withDefaults(
  defineProps<{
    risk: ReviewRisk
    action?: RiskAction
    selected?: boolean
  }>(),
  {
    action: 'pending',
    selected: false,
  },
)

defineEmits<{
  select: [id: string]
  locate: [risk: ReviewRisk]
  decide: [decision: 'accepted' | 'dismissed']
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

const evidencePage = computed(() => {
  const anchor = props.risk.evidence as Record<string, unknown> | undefined
  const page = Number(anchor?.page_number)
  return Number.isFinite(page) && page > 0 ? Math.round(page) : null
})

const evidencePrecision = computed(() => {
  const anchor = props.risk.evidence as Record<string, unknown> | undefined
  return anchor?.precision === 'page' ? '页级定位' : '精确定位'
})

const quoteText = computed(() => props.risk.quote || props.risk.currentText || '')
const reasonText = computed(() => props.risk.description || '')
const suggestionText = computed(() => props.risk.suggestion || '')
</script>

<template>
  <article
    class="risk-card"
    :class="[`risk-card--${risk.level}`, { 'risk-card--resolved': action !== 'pending', 'risk-card--selected': selected }]"
    :data-risk-id="risk.id"
    :data-action="action"
  >
    <button class="risk-card__main" type="button" :aria-label="`查看风险：${risk.title}`" @click="$emit('select', risk.id)">
      <span class="risk-card__heading">
        <span class="risk-card__level">
          <el-icon aria-hidden="true"><Warning /></el-icon>
          {{ levelLabel[risk.level] }}
        </span>
        <span class="risk-card__section">{{ risk.section }}</span>
        <span v-if="actionLabel" class="risk-card__action">
          <el-icon aria-hidden="true">
            <Check v-if="action === 'accepted'" />
            <Close v-else />
          </el-icon>
          {{ actionLabel }}
        </span>
      </span>

      <strong class="risk-card__title">{{ risk.title }}</strong>

      <span v-if="quoteText" class="risk-card__block">
        <b>原文引用</b>
        <span class="risk-card__quote">{{ quoteText }}</span>
      </span>

      <span v-if="reasonText" class="risk-card__block">
        <b>风险原因</b>
        <span>{{ reasonText }}</span>
      </span>

      <span v-if="suggestionText" class="risk-card__block risk-card__block--suggestion">
        <b>修改建议</b>
        <span>{{ suggestionText }}</span>
      </span>

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
    </button>

    <footer class="risk-card__footer">
      <span v-if="evidencePage !== null" class="risk-card__evidence">
        <el-icon aria-hidden="true"><Position /></el-icon>
        第 {{ evidencePage }} 页 · {{ evidencePrecision }}
      </span>
      <span class="risk-card__actions">
        <button
          v-if="risk.evidence"
          type="button"
          class="risk-card__btn"
          data-test="card-locate"
          :aria-label="`定位证据：${risk.title}`"
          @click="$emit('locate', risk)"
        >定位证据</button>
        <button
          v-if="action !== 'accepted'"
          type="button"
          class="risk-card__btn risk-card__btn--primary"
          data-test="card-accept"
          @click="$emit('decide', 'accepted')"
        >采纳建议</button>
        <button
          v-if="action !== 'dismissed'"
          type="button"
          class="risk-card__btn"
          data-test="card-dismiss"
          @click="$emit('decide', 'dismissed')"
        >忽略风险</button>
      </span>
    </footer>
  </article>
</template>

<style scoped>
.risk-card {
  display: flex;
  width: 100%;
  min-width: 0;
  flex-direction: column;
  gap: 8px;
  padding: 16px;
  border: 1px solid var(--outline-soft);
  border-radius: var(--radius-md);
  color: var(--ink);
  background: var(--surface);
  overflow-wrap: anywhere;
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

.risk-card--selected {
  border-color: var(--action);
  box-shadow: 0 0 0 1px var(--action), var(--shadow-sm);
  background: var(--action-subtle);
}

.risk-card__main {
  display: flex;
  width: 100%;
  flex-direction: column;
  gap: 8px;
  padding: 0;
  border: 0;
  color: inherit;
  background: transparent;
  text-align: left;
  cursor: pointer;
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
  white-space: nowrap;
}

.risk-card--high .risk-card__level {
  background: var(--danger);
}

.risk-card--medium .risk-card__level {
  background: var(--warning);
}

.risk-card--low .risk-card__level {
  background: var(--info, #909399);
}

.risk-card__section {
  min-width: 0;
  flex: 1;
  overflow: hidden;
  color: var(--ink-muted);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.risk-card__action {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--success);
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}

.risk-card__action .el-icon {
  font-size: 12px;
}

.risk-card__title {
  font-size: 14px;
}

.risk-card__block {
  display: flex;
  flex-direction: column;
  gap: 3px;
  font-size: 12px;
  line-height: 1.7;
}

.risk-card__block b {
  color: var(--ink-muted);
  font-size: 11px;
  font-weight: 700;
}

.risk-card__quote {
  padding: 8px 10px;
  border-left: 3px solid var(--outline-soft);
  background: var(--surface-low);
  color: var(--ink-muted);
}

.risk-card__block--suggestion {
  padding: 10px 12px;
  border: 1px dashed var(--action-outline);
  border-radius: var(--radius-sm);
  background: var(--action-soft);
}

.risk-card__block--suggestion b {
  color: var(--action);
}

.risk-card__comparison {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 11px;
  line-height: 1.7;
}

.risk-card__comparison b {
  margin-right: 6px;
  color: var(--ink-muted);
}

.risk-card__reference {
  color: var(--action);
}

.risk-card__footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--outline-soft);
}

.risk-card__evidence {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--ink-muted);
  font-size: 11px;
  white-space: nowrap;
}

.risk-card__actions {
  display: inline-flex;
  gap: 6px;
}

.risk-card__btn {
  min-height: 26px;
  padding: 3px 10px;
  border: 1px solid var(--outline-soft);
  border-radius: var(--radius-sm);
  color: var(--ink);
  background: var(--surface);
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
}

.risk-card__btn:hover {
  border-color: var(--action);
  color: var(--action);
}

.risk-card__btn--primary {
  color: var(--action);
}
</style>
