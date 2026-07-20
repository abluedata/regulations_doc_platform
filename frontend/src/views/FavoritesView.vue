<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, RefreshRight } from '@element-plus/icons-vue'
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
  <main class="enterprise-page favorites-page">
    <header class="page-header" data-test="page-header">
      <div class="page-header__copy">
        <h1>我的收藏</h1>
        <p>集中查看并管理重点问答记录</p>
      </div>
      <div class="page-header__actions">
        <el-tag type="info" effect="plain">{{ status || '正在读取收藏' }}</el-tag>
      </div>
    </header>

    <section class="surface-panel records-panel" aria-labelledby="favorites-results-heading">
      <div class="surface-panel__header compact-header">
        <div>
          <h2 id="favorites-results-heading">收藏记录</h2>
          <p>已选择 {{ selected.length }} 条</p>
        </div>
      </div>
      <div class="task-toolbar bulk-toolbar">
        <div class="task-toolbar__group">
          <el-button :icon="RefreshRight" @click="load">刷新</el-button>
        </div>
        <div class="task-toolbar__group task-toolbar__danger">
          <el-button
            data-test="delete-selected"
            type="danger"
            :icon="Delete"
            @click="onDelete"
          >
            删除选中
          </el-button>
        </div>
      </div>
      <div class="table-scroll">
        <SessionTable :rows="rows" :loading="loading" @selection-change="(s) => (selected = s)" />
      </div>
    </section>
  </main>
</template>
