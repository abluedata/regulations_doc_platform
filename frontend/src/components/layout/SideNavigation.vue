<script setup lang="ts">
import {
  ChatDotRound,
  Clock,
  Collection,
  DocumentCopy,
  Search,
  SetUp,
  Setting,
  Star,
  UploadFilled,
} from '@element-plus/icons-vue'
import type { Component } from 'vue'
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

defineProps<{
  open: boolean
}>()

const emit = defineEmits<{
  navigate: []
}>()

interface NavigationItem {
  label: string
  path: string
  icon: Component
  match?: (path: string) => boolean
}

const route = useRoute()
const router = useRouter()

const primaryNavigation: NavigationItem[] = [
  { label: '智能问答', path: '/', icon: ChatDotRound },
  {
    label: '知识库',
    path: '/docs',
    icon: Collection,
    match: (path) => path === '/docs' || path.startsWith('/docs/'),
  },
  { label: '历史记录', path: '/history', icon: Clock },
  { label: '我的收藏', path: '/favorites', icon: Star },
  {
    label: '详情管理',
    path: '/detail',
    icon: Setting,
    match: (path) => path.startsWith('/detail'),
  },
]

const reviewNavigation: NavigationItem[] = [
  { label: '文档上传', path: '/review/upload', icon: UploadFilled },
  { label: '范本选择', path: '/review/templates', icon: DocumentCopy },
  { label: '条款设置', path: '/review/rules', icon: SetUp },
  { label: '智能审查', path: '/review/console', icon: Search },
]

const activePath = computed(() => route.path)

function isActive(item: NavigationItem) {
  return item.match ? item.match(activePath.value) : activePath.value === item.path
}

async function navigate(item: NavigationItem) {
  if (!isActive(item)) {
    await router.push(item.path)
  }
  emit('navigate')
}
</script>

<template>
  <aside
    id="primary-navigation"
    class="side-navigation"
    :class="{ 'side-navigation--open': open }"
    aria-label="主导航"
  >
    <nav class="side-navigation__content">
      <section class="navigation-group" aria-labelledby="navigation-general">
        <h2 id="navigation-general" class="navigation-group__title">工作台</h2>
        <button
          v-for="item in primaryNavigation"
          :key="item.path"
          class="navigation-item"
          :class="{ 'navigation-item--active': isActive(item) }"
          type="button"
          :aria-current="isActive(item) ? 'page' : undefined"
          @click="navigate(item)"
        >
          <el-icon class="navigation-item__icon" aria-hidden="true">
            <component :is="item.icon" />
          </el-icon>
          <span>{{ item.label }}</span>
        </button>
      </section>

      <section class="navigation-group" aria-labelledby="navigation-review">
        <div class="navigation-group__heading">
          <h2 id="navigation-review" class="navigation-group__title">智能审查</h2>
          <span class="navigation-group__badge">4 步</span>
        </div>
        <button
          v-for="(item, index) in reviewNavigation"
          :key="item.path"
          class="navigation-item navigation-item--step"
          :class="{ 'navigation-item--active': isActive(item) }"
          type="button"
          :aria-current="isActive(item) ? 'step' : undefined"
          @click="navigate(item)"
        >
          <span class="navigation-item__step">{{ index + 1 }}</span>
          <el-icon class="navigation-item__icon" aria-hidden="true">
            <component :is="item.icon" />
          </el-icon>
          <span>{{ item.label }}</span>
        </button>
      </section>
    </nav>

    <div class="side-navigation__footer">
      <span class="side-navigation__footer-label">当前版本</span>
      <strong>Review Workspace 1.0</strong>
    </div>
  </aside>
</template>
