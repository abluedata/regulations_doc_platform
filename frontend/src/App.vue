<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import SideNavigation from '@/components/layout/SideNavigation.vue'
import TopHeader from '@/components/layout/TopHeader.vue'

const route = useRoute()
const menuOpen = ref(false)

watch(
  () => route.fullPath,
  () => {
    menuOpen.value = false
  },
)

function closeMenu() {
  menuOpen.value = false
}

function handleKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') closeMenu()
}

onMounted(() => window.addEventListener('keydown', handleKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', handleKeydown))
</script>

<template>
  <div class="app-shell">
    <TopHeader :menu-open="menuOpen" @toggle-menu="menuOpen = !menuOpen" />

    <div class="app-body">
      <SideNavigation :open="menuOpen" @navigate="closeMenu" />
      <button
        v-if="menuOpen"
        class="navigation-backdrop"
        type="button"
        aria-label="关闭导航菜单"
        @click="closeMenu"
      ></button>

      <main class="app-main">
        <div class="app-content">
          <router-view />
        </div>
      </main>
    </div>
  </div>
</template>
