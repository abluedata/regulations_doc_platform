<script setup lang="ts">
import { ref, watch } from 'vue'
import type { SessionRecord } from '@/types'
import { useRouter } from 'vue-router'
import { Collection, Connection, View } from '@element-plus/icons-vue'

const props = defineProps<{
  rows: SessionRecord[]
  loading?: boolean
}>()

const emit = defineEmits<{
  selectionChange: [rows: SessionRecord[]]
}>()

const router = useRouter()
const tableRef = ref()

watch(
  () => props.rows,
  () => {
    tableRef.value?.clearSelection?.()
  },
)

function short(s: string, n = 80) {
  const t = (s || '').replace(/\n/g, ' ')
  return t.length > n ? t.slice(0, n) + '...' : t
}

function routeLabel(row: SessionRecord) {
  return row.has_web ? '网络' : '本地'
}

function onSelect(selection: SessionRecord[]) {
  emit('selectionChange', selection)
}

function goDetail(row: SessionRecord) {
  router.push({ name: 'detail', params: { id: row.id } })
}
</script>

<template>
  <el-table
    ref="tableRef"
    :data="rows"
    v-loading="loading"
    stripe
    height="520"
    class="session-table"
    empty-text="暂无会话记录"
    @selection-change="onSelect"
    @row-click="goDetail"
  >
    <el-table-column type="selection" width="48" />
    <el-table-column prop="id" label="ID" min-width="180" show-overflow-tooltip />
    <el-table-column prop="timestamp" label="时间" width="170" />
    <el-table-column label="问题" min-width="160" show-overflow-tooltip>
      <template #default="{ row }">{{ short(row.question, 80) }}</template>
    </el-table-column>
    <el-table-column label="回答摘要" min-width="200" show-overflow-tooltip>
      <template #default="{ row }">{{ short(row.answer, 120) }}</template>
    </el-table-column>
    <el-table-column label="来源" width="96" align="center">
      <template #default="{ row }">
        <el-tag size="small" :type="row.has_web ? 'primary' : 'info'" effect="plain">
          <el-icon aria-hidden="true"><Connection v-if="row.has_web" /><Collection v-else /></el-icon>
          <span>{{ routeLabel(row) }}</span>
        </el-tag>
      </template>
    </el-table-column>
    <el-table-column label="操作" width="96" fixed="right">
      <template #default="{ row }">
        <el-button link type="primary" :icon="View" @click.stop="goDetail(row)">查看</el-button>
      </template>
    </el-table-column>
  </el-table>
</template>
