<script setup lang="ts">
import { Lock, Money, SetUp, TrendCharts } from '@element-plus/icons-vue'
import { computed } from 'vue'
import type { ReviewClause } from '@/types'

const props = defineProps<{
  clause: ReviewClause
}>()

defineEmits<{
  toggle: [id: string]
  edit: [clause: ReviewClause]
}>()

const clauseIcon = computed(() => {
  if (props.clause.id.includes('payment')) return Money
  if (props.clause.id.includes('liability')) return TrendCharts
  if (props.clause.group === 'compliance') return Lock
  return SetUp
})
</script>

<template>
  <article
    class="clause-card"
    :class="{ 'clause-card--disabled': clause.disabled }"
    :data-clause-id="clause.id"
  >
    <div class="clause-card__heading">
      <span class="clause-card__icon" aria-hidden="true">
        <el-icon><component :is="clauseIcon" /></el-icon>
      </span>
      <label class="clause-card__toggle">
        <span class="clause-card__toggle-label">
          {{ clause.enabled ? `停用${clause.title}` : `启用${clause.title}` }}
        </span>
        <input
          type="checkbox"
          :checked="clause.enabled"
          :disabled="clause.disabled"
          @change="$emit('toggle', clause.id)"
        />
      </label>
    </div>

    <div class="clause-card__body">
      <h3>{{ clause.title }}</h3>
      <p>{{ clause.description }}</p>
    </div>

    <div class="clause-card__footer">
      <span v-if="clause.priority === 'high'" class="clause-card__tag clause-card__tag--danger">
        高优先级
      </span>
      <span v-else-if="clause.threshold" class="clause-card__tag">
        {{ clause.threshold }}
      </span>
      <span v-else-if="clause.disabled" class="clause-card__disabled-label">已禁用</span>
      <span v-else class="clause-card__status">
        <span aria-hidden="true"></span>
        正在监控
      </span>
      <span class="clause-card__footer-actions">
        <span v-if="clause.version" class="clause-card__version">v{{ clause.version }}</span>
        <button class="clause-card__edit" type="button" data-test="clause-edit" :aria-label="`编辑${clause.title}`" @click.stop="$emit('edit', clause)">编辑</button>
      </span>
    </div>
  </article>
</template>

<style scoped>
.clause-card {
  display: flex;
  min-height: 190px;
  flex-direction: column;
  padding: 18px;
  border: 1px solid var(--outline-soft);
  border-radius: var(--radius-lg);
  background: var(--surface);
  box-shadow: var(--shadow-sm);
}

.clause-card--disabled {
  opacity: 0.58;
  filter: grayscale(0.7);
}

.clause-card__heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 16px;
}

.clause-card__icon {
  display: grid;
  width: 38px;
  height: 38px;
  place-items: center;
  border-radius: var(--radius-md);
  color: var(--action);
  background: var(--action-soft);
  font-size: 20px;
}

.clause-card__toggle {
  position: relative;
  display: inline-flex;
  min-width: 44px;
  min-height: var(--control-height);
  align-items: center;
  justify-content: flex-end;
  cursor: pointer;
}

.clause-card__toggle:has(input:disabled) {
  cursor: not-allowed;
}

.clause-card__toggle-label {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  clip-path: inset(50%);
  white-space: nowrap;
}

.clause-card__toggle input {
  width: 42px;
  height: 24px;
  margin: 0;
  border: 1px solid var(--outline);
  border-radius: 999px;
  appearance: none;
  background:
    radial-gradient(circle at 11px center, #ffffff 0 8px, transparent 9px),
    var(--outline);
  cursor: inherit;
  transition: background 160ms ease-out;
}

.clause-card__toggle input:checked {
  border-color: var(--action);
  background:
    radial-gradient(circle at 29px center, #ffffff 0 8px, transparent 9px),
    var(--action);
}

.clause-card__toggle input:focus-visible {
  outline: 2px solid var(--action);
  outline-offset: 2px;
}

.clause-card__body {
  flex: 1;
}

.clause-card__body h3 {
  margin: 0 0 6px;
  font-size: 16px;
}

.clause-card__body p {
  margin: 0;
  color: var(--ink-muted);
  font-size: 13px;
  line-height: 1.6;
}

.clause-card__footer {
  display: flex;
  align-items: center;
  min-height: 24px;
  margin-top: 16px;
}

.clause-card__tag,
.clause-card__disabled-label {
  padding: 3px 7px;
  border-radius: var(--radius-sm);
  color: var(--ink-muted);
  background: var(--surface-low);
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
}

.clause-card__tag--danger {
  color: var(--danger);
  background: #ffdad6;
}

.clause-card__disabled-label {
  color: #718196;
  background: transparent;
}

.clause-card__status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--ink-muted);
  font-size: 11px;
  font-weight: 600;
}

.clause-card__status span {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--success);
}

.clause-card__footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.clause-card__footer-actions {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.clause-card__version {
  color: var(--ink-muted);
  font-size: 10px;
}

.clause-card__edit {
  min-height: 24px;
  padding: 2px 10px;
  border: 1px solid var(--outline-soft);
  border-radius: var(--radius-sm);
  color: var(--action);
  background: var(--surface);
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
}

.clause-card__edit:hover {
  border-color: var(--action);
  background: var(--action-soft);
}
</style>
