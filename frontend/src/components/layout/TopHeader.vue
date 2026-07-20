<script setup lang="ts">
import { DocumentChecked, Menu } from '@element-plus/icons-vue'

defineProps<{
  menuOpen: boolean
}>()

defineEmits<{
  toggleMenu: []
}>()
</script>

<template>
  <header class="top-header">
    <div class="top-header__leading">
      <button
        class="top-header__menu-button"
        type="button"
        :aria-expanded="menuOpen"
        aria-controls="primary-navigation"
        :aria-label="menuOpen ? '关闭导航菜单' : '打开导航菜单'"
        @click="$emit('toggleMenu')"
      >
        <el-icon aria-hidden="true"><Menu /></el-icon>
      </button>

      <RouterLink class="product-brand" to="/" aria-label="审核智规首页">
        <span class="product-brand__mark" aria-hidden="true">
          <el-icon><DocumentChecked /></el-icon>
        </span>
        <span class="product-brand__copy">
          <strong>审核智规</strong>
          <small>法规文档智能工作台</small>
        </span>
      </RouterLink>
    </div>

    <div class="top-header__meta">
      <span class="top-header__status">
        <span class="top-header__status-dot" aria-hidden="true"></span>
        服务正常
      </span>
      <span class="top-header__divider" aria-hidden="true"></span>
      <span class="top-header__workspace">企业工作区</span>
    </div>
  </header>
</template>
