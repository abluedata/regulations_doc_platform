<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import SessionTable from '@/components/SessionTable.vue'
import type { SessionRecord } from '@/types'
import { batchDeleteFavorites, listFavorites } from '@/api/favorites'

const rows = ref<SessionRecord[]>([])
const loading = ref(false)
const selected = ref<SessionRecord[]>([])
const status = ref('')

async function load() {
  loading.value = true
  try {
    const { data } = await listFavorites({ page: 1, page_size: 200 })
    rows.value = data.items
    status.value = `共 ${data.total} 条收藏`
  } catch (e: any) {
    ElMessage.error(e.message || '加载失败')
  } finally {
    loading.value = false
  }
}

async function onDelete() {
  if (!selected.value.length) {
    ElMessage.warning('请先勾选记录')
    return
  }
  try {
    await ElMessageBox.confirm(`确认取消收藏 ${selected.value.length} 条？`, '确认', {
      type: 'warning',
    })
    const { data } = await batchDeleteFavorites(selected.value.map((r) => r.id))
    ElMessage.success(data.message)
    await load()
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error(e.message || '删除失败')
  }
}

onMounted(load)
</script>

<template>
  <div class="page-card">
    <div class="toolbar-row">
      <el-button @click="load">↺ 刷新</el-button>
      <el-button type="danger" @click="onDelete">✕ 删除选中</el-button>
      <span class="status-text">{{ status }}</span>
    </div>
    <SessionTable :rows="rows" :loading="loading" @selection-change="(s) => (selected = s)" />
  </div>
</template>
