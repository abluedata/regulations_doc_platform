<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { UploadRequestOptions } from 'element-plus'
import {
  Close,
  Delete,
  DocumentAdd,
  RefreshRight,
  Search,
  View,
} from '@element-plus/icons-vue'
import type { DocRecord } from '@/types'
import { deleteDoc, listDocs, reparseDoc, uploadDoc } from '@/api/knowledge/docs'

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
  <main class="enterprise-page docs-page">
    <header class="page-header" data-test="page-header">
      <div class="page-header__copy">
        <h1>知识库</h1>
        <p>上传合同与条款文档，跟踪解析状态并维护企业检索库</p>
      </div>
      <div class="page-header__actions">
        <el-tag v-if="hasProcessing" type="warning" effect="plain">解析任务进行中</el-tag>
        <el-tag v-else type="success" effect="plain">知识库可用</el-tag>
      </div>
    </header>

    <section class="upload-section" aria-labelledby="upload-heading">
      <div class="section-heading">
        <div>
          <h2 id="upload-heading">上传文档</h2>
          <p>支持 PDF、DOCX；单个任务完成后会自动刷新列表</p>
        </div>
        <span v-if="uploading" class="section-status">{{ uploadPct }}%</span>
      </div>
      <el-upload
        class="docs-uploader"
        drag
        :show-file-list="false"
        :http-request="customUpload"
        accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        multiple
        :disabled="uploading"
        aria-label="上传 PDF 或 DOCX 文档"
      >
        <div class="upload-inner">
          <el-icon class="upload-icon" aria-hidden="true"><DocumentAdd /></el-icon>
          <div class="upload-main">
            {{ uploading ? `上传中 ${uploadPct}%` : '拖拽文档到此处，或点击选择文件' }}
          </div>
          <div class="upload-hint">
            数字版 PDF 与 DOCX 可直接解析；CPU 解析可能需要数分钟
          </div>
          <el-progress
            v-if="uploading"
            class="upload-progress"
            :percentage="uploadPct"
            :show-text="false"
          />
        </div>
      </el-upload>
    </section>

    <section class="surface-panel docs-list-panel" aria-labelledby="docs-list-heading">
      <div class="surface-panel__header docs-list-header">
        <div>
          <h2 id="docs-list-heading">文档列表</h2>
          <p>{{ statusText || '正在读取知识库状态' }}</p>
        </div>
        <span v-if="hasProcessing" class="live-status live-status--active">
          <span aria-hidden="true" />自动更新
        </span>
      </div>

      <div class="task-toolbar docs-toolbar" data-test="docs-toolbar">
        <div class="task-toolbar__group task-toolbar__filters">
          <el-select
            v-model="statusFilter"
            aria-label="文档状态"
            style="width: 140px"
            @change="onFilter"
          >
            <el-option label="全部状态" value="all" />
            <el-option label="处理中" value="processing" />
            <el-option label="已入库" value="ready" />
            <el-option label="失败" value="failed" />
            <el-option label="排队中" value="queued" />
          </el-select>
          <el-input
            v-model="searchQ"
            aria-label="搜索文件名"
            placeholder="搜索文件名"
            clearable
            style="width: 220px"
            @keyup.enter="onFilter"
          />
          <el-button type="primary" :icon="Search" @click="onFilter">搜索</el-button>
          <el-button :icon="Close" @click="onClearFilter">清除</el-button>
        </div>
        <div class="task-toolbar__group">
          <el-button :icon="RefreshRight" @click="loadAndPoll">刷新</el-button>
        </div>
      </div>

      <div class="table-scroll">
        <el-table
          :data="rows"
          v-loading="loading"
          stripe
          height="520"
          empty-text="还没有文档。上传后可在此跟踪解析进度"
          class="docs-table"
          @row-click="goPreview"
        >
          <el-table-column prop="filename" label="文件名" min-width="220" show-overflow-tooltip>
            <template #default="{ row }">
              <span class="linkish">{{ row.filename }}</span>
            </template>
          </el-table-column>
          <el-table-column label="类型" width="80" align="center">
            <template #default="{ row }">
              <el-tag size="small" type="info" effect="plain">{{ (row.ext || '').toUpperCase() || '—' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="112" align="center">
            <template #default="{ row }">
              <el-tag size="small" :type="statusTagType(row.status)">
                {{ row.stage_label || row.status }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="阶段 / 说明" min-width="170" show-overflow-tooltip>
            <template #default="{ row }">
              <span v-if="row.error" class="err-text">{{ row.error }}</span>
              <span v-else class="muted">{{ row.stage_label || '—' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="页 / 块" width="112" align="center">
            <template #default="{ row }">{{ formatPagesChunks(row) }}</template>
          </el-table-column>
          <el-table-column label="大小" width="96" align="center">
            <template #default="{ row }">{{ formatSize(row.file_size) }}</template>
          </el-table-column>
          <el-table-column prop="created_at" label="上传时间" width="170" />
          <el-table-column label="操作" width="216" fixed="right">
            <template #default="{ row }">
              <div class="row-actions" @click.stop>
                <el-button link type="primary" :icon="View" @click="goPreview(row)">预览</el-button>
                <el-button link :icon="RefreshRight" @click="onReparse(row)">重析</el-button>
                <el-button link type="danger" :icon="Delete" @click="onDelete(row)">删除</el-button>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </section>
  </main>
</template>

<style scoped>
.docs-uploader {
  width: 100%;
}

.docs-uploader :deep(.el-upload) {
  width: 100%;
}

.docs-uploader :deep(.el-upload-dragger) {
  width: 100%;
  min-height: 188px;
  padding: 34px 20px;
  border: 1px dashed var(--outline);
  border-radius: var(--radius-lg);
  background: var(--surface);
  transition: border-color 0.18s ease, background 0.18s ease;
}

.docs-uploader :deep(.el-upload-dragger:hover) {
  border-color: var(--action);
  background: #f5f8ff;
}

.upload-inner {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
}

.upload-icon {
  width: 44px;
  height: 44px;
  margin-bottom: 6px;
  border-radius: var(--radius-md);
  color: var(--action);
  background: var(--action-soft);
  font-size: 24px;
}

.upload-main {
  font-size: 15px;
  font-weight: 700;
  color: var(--ink);
}

.upload-hint {
  font-size: 12px;
  color: var(--ink-muted);
  max-width: 42rem;
  text-align: center;
  line-height: 1.5;
}

.upload-progress {
  width: min(420px, 100%);
  margin-top: 8px;
}

.docs-table {
  cursor: pointer;
}

.linkish {
  color: var(--action);
  font-weight: 600;
}

.err-text {
  color: var(--danger);
  font-size: 13px;
}

.muted {
  color: var(--ink-muted);
  font-size: 13px;
}

.row-actions {
  display: flex;
  gap: 2px;
  flex-wrap: wrap;
}

@media (max-width: 600px) {
  .docs-uploader :deep(.el-upload-dragger) {
    min-height: 164px;
    padding: 26px 14px;
  }

  .upload-main {
    font-size: 14px;
  }
}
</style>
