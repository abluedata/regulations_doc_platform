<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Close, Delete, RefreshRight, Search, Star } from '@element-plus/icons-vue'
import SessionTable from '@/components/knowledge/SessionTable.vue'
import type { SessionRecord } from '@/types'
import {
  batchDeleteHistory,
  batchFavoriteHistory,
  clearHistory,
  listHistory,
} from '@/api/knowledge/history'

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
  <main class="enterprise-page history-page">
    <header class="page-header" data-test="page-header">
      <div class="page-header__copy">
        <h1>历史记录</h1>
        <p>检索、收藏并维护智能问答会话</p>
      </div>
      <div class="page-header__actions">
        <el-tag type="info" effect="plain">{{ status || '正在读取记录' }}</el-tag>
      </div>
    </header>

    <section class="surface-panel filter-panel" aria-labelledby="history-filter-heading">
      <div class="surface-panel__header compact-header">
        <div>
          <h2 id="history-filter-heading">筛选记录</h2>
          <p>可按会话 ID、问题内容和日期范围组合查询</p>
        </div>
      </div>
      <div class="task-toolbar history-search" data-test="history-search">
        <div class="task-toolbar__group task-toolbar__filters">
          <el-input
            v-model="searchId"
            aria-label="按会话 ID 搜索"
            placeholder="ID 搜索（模糊）"
            clearable
            style="width: 160px"
          />
          <el-input
            v-model="searchQ"
            aria-label="按问题搜索"
            placeholder="问题搜索（模糊）"
            clearable
            style="width: 220px"
          />
          <el-date-picker
            v-model="dateStart"
            type="date"
            aria-label="开始日期"
            placeholder="开始日期"
            value-format="YYYY-MM-DD"
            style="width: 150px"
          />
          <el-date-picker
            v-model="dateEnd"
            type="date"
            aria-label="结束日期"
            placeholder="结束日期"
            value-format="YYYY-MM-DD"
            style="width: 150px"
          />
        </div>
        <div class="task-toolbar__group">
          <el-button type="primary" :icon="Search" @click="load">搜索</el-button>
          <el-button :icon="Close" @click="onClearSearch">清除</el-button>
        </div>
      </div>
    </section>

    <section class="surface-panel records-panel" aria-labelledby="history-results-heading">
      <div class="surface-panel__header compact-header">
        <div>
          <h2 id="history-results-heading">会话记录</h2>
          <p>已选择 {{ selected.length }} 条</p>
        </div>
      </div>
      <div class="task-toolbar bulk-toolbar">
        <div class="task-toolbar__group">
          <el-button :icon="RefreshRight" @click="load">刷新</el-button>
          <el-button data-test="favorite-selected" :icon="Star" @click="onFavorite">
            收藏选中
          </el-button>
        </div>
        <div class="task-toolbar__group task-toolbar__danger">
          <el-button type="danger" plain :icon="Delete" @click="onClearAll">清空所有</el-button>
          <el-button data-test="delete-selected" type="danger" :icon="Delete" @click="onDelete">
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
