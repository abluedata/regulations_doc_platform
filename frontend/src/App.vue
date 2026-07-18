<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()

const active = computed(() => {
  const name = route.name as string
  if (name === 'detail') return '/detail'
  if (name === 'docs' || name === 'doc-preview') return '/docs'
  return route.path
})

function onSelect(index: string) {
  router.push(index)
}
</script>

<template>
  <div class="app-shell">
    <header class="app-header">
      <div class="brand">
        保险智答
        <span>AI × 保险知识库</span>
      </div>
      <el-menu
        mode="horizontal"
        :ellipsis="false"
        :default-active="active"
        @select="onSelect"
      >
        <el-menu-item index="/">💬 智能问答</el-menu-item>
        <el-menu-item index="/docs">📚 知识库</el-menu-item>
        <el-menu-item index="/history">🕘 历史记录</el-menu-item>
        <el-menu-item index="/favorites">☆ 收藏</el-menu-item>
        <el-menu-item index="/detail">⚙ 详情管理</el-menu-item>
      </el-menu>
    </header>
    <main class="app-main">
      <router-view />
    </main>
  </div>
</template>
