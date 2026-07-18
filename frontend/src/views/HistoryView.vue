<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import SessionTable from '@/components/SessionTable.vue'
import type { SessionRecord } from '@/types'
import {
  batchDeleteHistory,
  batchFavoriteHistory,
  clearHistory,
  listHistory,
} from '@/api/history'

const rows = ref<SessionRecord[]>([])
const total = ref(0)
const loading = ref(false)
const selected = ref<SessionRecord[]>([])
const status = ref('')

const searchId = ref('')
const searchQ = ref('')
const dateStart = ref('')
const dateEnd = ref('')

async function load() {
  loading.value = true
  try {
    const { data } = await listHistory({
      id: searchId.value || undefined,
      q: searchQ.value || undefined,
      date_start: dateStart.value || undefined,
      date_end: dateEnd.value || undefined,
      page: 1,
      page_size: 200,
    })
    rows.value = data.items
    total.value = data.total
    const filtered = !!(searchId.value || searchQ.value || dateStart.value || dateEnd.value)
    status.value = `共 ${data.total} 条记录${filtered ? '（已筛选）' : ''}`
  } catch (e: any) {
    ElMessage.error(e.message || '加载失败')
  } finally {
    loading.value = false
  }
}

function onClearSearch() {
  searchId.value = ''
  searchQ.value = ''
  dateStart.value = ''
  dateEnd.value = ''
  load()
}

async function onFavorite() {
  if (!selected.value.length) {
    ElMessage.warning('请先勾选记录')
    return
  }
  try {
    const { data } = await batchFavoriteHistory(selected.value.map((r) => r.id))
    ElMessage.success(data.message)
    status.value = data.message
  } catch (e: any) {
    ElMessage.error(e.message)
  }
}

async function onDelete() {
  if (!selected.value.length) {
    ElMessage.warning('请先勾选记录')
    return
  }
  try {
    await ElMessageBox.confirm(`确认删除选中的 ${selected.value.length} 条？`, '删除确认', {
      type: 'warning',
    })
    const { data } = await batchDeleteHistory(selected.value.map((r) => r.id))
    ElMessage.success(data.message)
    await load()
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error(e.message || '删除失败')
  }
}

async function onClearAll() {
  try {
    await ElMessageBox.confirm('确认清空全部历史？（不影响收藏）', '清空确认', {
      type: 'warning',
    })
    const { data } = await clearHistory()
    ElMessage.success(data.message)
    await load()
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error(e.message || '清空失败')
  }
}

onMounted(load)
</script>

<template>
  <div class="page-card">
    <div class="toolbar-row">
      <el-input v-model="searchId" placeholder="ID 搜索（模糊）" clearable style="width: 160px" />
      <el-input v-model="searchQ" placeholder="问题搜索（模糊）" clearable style="width: 220px" />
      <el-date-picker
        v-model="dateStart"
        type="date"
        placeholder="开始日期"
        value-format="YYYY-MM-DD"
        style="width: 150px"
      />
      <el-date-picker
        v-model="dateEnd"
        type="date"
        placeholder="结束日期"
        value-format="YYYY-MM-DD"
        style="width: 150px"
      />
      <el-button type="primary" @click="load">🔍 搜索</el-button>
      <el-button @click="onClearSearch">✕ 清除</el-button>
    </div>

    <div class="toolbar-row">
      <el-button @click="load">↺ 刷新</el-button>
      <el-button @click="onFavorite">☆ 收藏选中</el-button>
      <el-button type="danger" plain @click="onClearAll">✕ 清空所有</el-button>
      <el-button type="danger" @click="onDelete">✕ 删除选中</el-button>
      <span class="status-text">{{ status }}</span>
    </div>

    <SessionTable :rows="rows" :loading="loading" @selection-change="(s) => (selected = s)" />
  </div>
</template>
