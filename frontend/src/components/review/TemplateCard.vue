<script setup lang="ts">
import {
  Briefcase,
  Document,
  Files,
  House,
  Key,
  Lock,
  Medal,
} from '@element-plus/icons-vue'
import type { Component } from 'vue'
import type { ReviewTemplate } from '@/types'

const props = withDefaults(
  defineProps<{
    template: ReviewTemplate
    selected?: boolean
  }>(),
  {
    selected: false,
  },
)

defineEmits<{
  select: [id: string]
}>()

const iconMap: Record<string, Component> = {
  gavel: Medal,
  handshake: Briefcase,
  badge: Files,
  copyright: Key,
  real_estate_agent: House,
  lock: Lock,
}

function templateIcon() {
  return iconMap[props.template.icon] ?? Document
}
</script>

<template>
  <button
    class="template-card"
    :class="{ 'template-card--selected': selected }"
    type="button"
    :data-template-id="template.id"
    :aria-pressed="selected"
    @click="$emit('select', template.id)"
  >
    <span class="template-card__heading">
      <span class="template-card__icon" aria-hidden="true">
        <el-icon><component :is="templateIcon()" /></el-icon>
      </span>
      <span v-if="template.popular" class="template-card__popular">热门</span>
    </span>

    <span class="template-card__body">
      <strong>{{ template.name }}</strong>
      <span>{{ template.description }}</span>
    </span>

    <span class="template-card__meta">
      <span>{{ template.checks }} AI 检查项</span>
      <span>{{ template.category }}</span>
    </span>
  </button>
</template>

<style scoped>
.template-card {
  display: flex;
  width: 100%;
  min-height: 224px;
  flex-direction: column;
  gap: 18px;
  padding: 18px;
  border: 1px solid var(--outline-soft);
  border-radius: var(--radius-lg);
  color: var(--ink);
  background: var(--surface);
  box-shadow: var(--shadow-sm);
  text-align: left;
  cursor: pointer;
  transition:
    border-color 160ms ease-out,
    box-shadow 160ms ease-out,
    transform 160ms ease-out;
}

.template-card:hover {
  border-color: #8fb0e9;
  box-shadow: 0 8px 20px rgba(11, 28, 48, 0.1);
  transform: translateY(-2px);
}

.template-card--selected {
  border-color: var(--action);
  box-shadow: 0 0 0 2px var(--action);
}

.template-card__heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
}

.template-card__icon {
  display: grid;
  width: 48px;
  height: 48px;
  place-items: center;
  border-radius: var(--radius-md);
  color: var(--action);
  background: var(--action-soft);
  font-size: 26px;
}

.template-card__popular,
.template-card__meta span {
  padding: 3px 7px;
  border-radius: var(--radius-sm);
  font-size: 10px;
  font-weight: 700;
}

.template-card__popular {
  color: var(--action);
  background: var(--action-soft);
}

.template-card__body {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 6px;
}

.template-card__body strong {
  font-size: 17px;
}

.template-card__body > span {
  color: var(--ink-muted);
  font-size: 13px;
  line-height: 1.65;
}

.template-card__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding-top: 14px;
  border-top: 1px solid var(--outline-soft);
}

.template-card__meta span {
  color: var(--ink-muted);
  background: var(--surface-low);
  text-transform: uppercase;
}
</style>
