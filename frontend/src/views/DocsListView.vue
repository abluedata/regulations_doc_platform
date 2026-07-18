<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { UploadRequestOptions } from 'element-plus'
import type { DocRecord } from '@/types'
import { deleteDoc, listDocs, reparseDoc, uploadDoc } from '@/api/docs'

const router = useRouter()
const rows = ref<DocRecord[]>([])
const total = ref(0)
const loading = ref(false)
const uploading = ref(false)
const uploadPct = ref(0)
const statusFilter = ref('all')
const searchQ = ref('')
const statusText = ref('')

let pollTimer: ReturnType<typeof setInterval> | null = null

const hasProcessing = computed(() =>
  rows.value.some((r) =>
    ['uploaded', 'queued', 'parsing', 'normalizing', 'chunking', 'indexing'].includes(
      r.status,
    ),
  ),
)

async function load() {
  loading.value = true
  try {
    const { data } = await listDocs({
      q: searchQ.value || undefined,
      status: statusFilter.value === 'all' ? undefined : statusFilter.value,
      page: 1,
      page_size: 100,
    })
    rows.value = data.items
    total.value = data.total
    statusText.value = `共 ${data.total} 份文档`
  } catch (e: any) {
    ElMessage.error(e.message || '加载失败')
  } finally {
    loading.value = false
  }
}

function syncPoll() {
  if (hasProcessing.value) {
    if (!pollTimer) {
      pollTimer = setInterval(() => {
        load()
      }, 2500)
    }
  } else if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

async function loadAndPoll() {
  await load()
  syncPoll()
}

function statusTagType(status: string) {
  if (status === 'ready') return 'success'
  if (status === 'failed' || status === 'needs_ocr') return 'danger'
  if (status === 'queued' || status === 'uploaded') return 'info'
  return 'warning'
}

function formatSize(n?: number | null) {
  if (n == null) return '—'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

function formatPagesChunks(row: DocRecord) {
  if (row.status !== 'ready' && row.page_count == null && row.chunk_count == null) {
    return '—'
  }
  const p = row.page_count != null ? `${row.page_count} 页` : '—'
  const c = row.chunk_count != null ? `${row.chunk_count} 块` : '—'
  return `${p} / ${c}`
}

async function customUpload(opt: UploadRequestOptions) {
  const file = opt.file as File
  const name = file.name.toLowerCase()
  if (name.endsWith('.doc') && !name.endsWith('.docx')) {
    ElMessage.error('暂不支持 .doc，请另存为 .docx 后上传')
    opt.onError?.(new Error('unsupported') as any)
    return
  }
  if (!name.endsWith('.pdf') && !name.endsWith('.docx')) {
    ElMessage.error('仅支持 PDF、DOCX')
    opt.onError?.(new Error('unsupported') as any)
    return
  }

  uploading.value = true
  uploadPct.value = 0
  try {
    const { data } = await uploadDoc(file, (pct) => {
      uploadPct.value = pct
    })
    ElMessage.success(data.message || '已上传')
    opt.onSuccess?.(data as any)
    await loadAndPoll()
  } catch (e: any) {
    ElMessage.error(e.message || '上传失败')
    opt.onError?.(e)
  } finally {
    uploading.value = false
    uploadPct.value = 0
  }
}

function goPreview(row: DocRecord) {
  router.push({ name: 'doc-preview', params: { id: row.id } })
}

async function onReparse(row: DocRecord) {
  try {
    await ElMessageBox.confirm(
      '将清除旧索引并按当前文件重新解析，是否继续？',
      '重新解析',
      { type: 'warning' },
    )
    const { data } = await reparseDoc(row.id)
    ElMessage.success(data.message)
    await loadAndPoll()
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error(e.message || '操作失败')
  }
}

async function onDelete(row: DocRecord) {
  try {
    await ElMessageBox.confirm(
      '删除后将同时移除本地文件与检索索引，且不可恢复。',
      '删除确认',
      { type: 'warning' },
    )
    const { data } = await deleteDoc(row.id)
    ElMessage.success(data.message)
    await loadAndPoll()
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error(e.message || '删除失败')
  }
}

function onFilter() {
  loadAndPoll()
}

function onClearFilter() {
  searchQ.value = ''
  statusFilter.value = 'all'
  loadAndPoll()
}

onMounted(loadAndPoll)
onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<template>
  <div class="page-card docs-page">
    <div class="docs-header">
      <div>
        <h2 class="docs-title">知识库</h2>
        <p class="docs-sub">上传合同与条款文档，自动解析并写入检索库</p>
      </div>
    </div>

    <el-upload
      class="docs-uploader"
      drag
      :show-file-list="false"
      :http-request="customUpload"
      accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
      multiple
      :disabled="uploading"
    >
      <div class="upload-inner">
        <div class="upload-icon">📄</div>
        <div class="upload-main">
          {{ uploading ? `上传中 ${uploadPct}%…` : '将 PDF 或 DOCX 拖拽到此处，或点击选择' }}
        </div>
        <div class="upload-hint">
          支持数字版 PDF、DOCX；解析在 CPU 上可能需要数分钟，可稍后回来查看
        </div>
      </div>
    </el-upload>

    <div class="toolbar-row docs-toolbar">
      <el-select v-model="statusFilter" style="width: 140px" @change="onFilter">
        <el-option label="全部状态" value="all" />
        <el-option label="处理中" value="processing" />
        <el-option label="已入库" value="ready" />
        <el-option label="失败" value="failed" />
        <el-option label="排队中" value="queued" />
      </el-select>
      <el-input
        v-model="searchQ"
        placeholder="搜索文件名"
        clearable
        style="width: 220px"
        @keyup.enter="onFilter"
      />
      <el-button type="primary" @click="onFilter">搜索</el-button>
      <el-button @click="onClearFilter">清除</el-button>
      <el-button @click="loadAndPoll">刷新</el-button>
      <span class="status-text">
        {{ statusText }}
        <template v-if="hasProcessing"> · 正在处理，列表会自动更新</template>
      </span>
    </div>

    <el-table
      :data="rows"
      v-loading="loading"
      border
      stripe
      height="480"
      empty-text="还没有文档。上传后可在此跟踪解析进度"
      @row-click="goPreview"
      class="docs-table"
    >
      <el-table-column prop="filename" label="文件名" min-width="200" show-overflow-tooltip>
        <template #default="{ row }">
          <span class="linkish">{{ row.filename }}</span>
        </template>
      </el-table-column>
      <el-table-column label="类型" width="80" align="center">
        <template #default="{ row }">
          <el-tag size="small" type="info">{{ (row.ext || '').toUpperCase() || '—' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="110" align="center">
        <template #default="{ row }">
          <el-tag size="small" :type="statusTagType(row.status)">
            {{ row.stage_label || row.status }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="阶段 / 说明" min-width="160" show-overflow-tooltip>
        <template #default="{ row }">
          <span v-if="row.error" class="err-text">{{ row.error }}</span>
          <span v-else class="muted">{{ row.stage_label || '—' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="页 / 块" width="110" align="center">
        <template #default="{ row }">{{ formatPagesChunks(row) }}</template>
      </el-table-column>
      <el-table-column label="大小" width="90" align="center">
        <template #default="{ row }">{{ formatSize(row.file_size) }}</template>
      </el-table-column>
      <el-table-column prop="created_at" label="上传时间" width="170" />
      <el-table-column label="操作" width="200" fixed="right">
        <template #default="{ row }">
          <div class="row-actions" @click.stop>
            <el-button link type="primary" @click="goPreview(row)">预览</el-button>
            <el-button link @click="onReparse(row)">重析</el-button>
            <el-button link type="danger" @click="onDelete(row)">删除</el-button>
          </div>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<style scoped>
.docs-header {
  margin-bottom: 12px;
}

.docs-title {
  margin: 0;
  font-size: 1.25rem;
  font-weight: 700;
  color: var(--text);
  text-wrap: balance;
}

.docs-sub {
  margin: 6px 0 0;
  font-size: 13px;
  color: var(--muted);
}

.docs-uploader {
  width: 100%;
  margin-bottom: 14px;
}

.docs-uploader :deep(.el-upload) {
  width: 100%;
}

.docs-uploader :deep(.el-upload-dragger) {
  width: 100%;
  padding: 28px 16px;
  border-radius: 12px;
  border-color: var(--border);
  background: #fafbfc;
  transition: border-color 0.18s ease, background 0.18s ease;
}

.docs-uploader :deep(.el-upload-dragger:hover) {
  border-color: var(--primary);
  background: var(--user-bg);
}

.upload-inner {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
}

.upload-icon {
  font-size: 28px;
  line-height: 1;
  margin-bottom: 4px;
}

.upload-main {
  font-size: 15px;
  font-weight: 600;
  color: var(--text);
}

.upload-hint {
  font-size: 12px;
  color: var(--muted);
  max-width: 42rem;
  text-align: center;
  line-height: 1.5;
}

.docs-toolbar {
  margin-bottom: 12px;
}

.docs-table {
  cursor: pointer;
}

.linkish {
  color: var(--primary);
  font-weight: 500;
}

.err-text {
  color: #dc2626;
  font-size: 13px;
}

.muted {
  color: var(--muted);
  font-size: 13px;
}

.row-actions {
  display: flex;
  gap: 2px;
  flex-wrap: wrap;
}
</style>
