<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { marked } from 'marked'
import type { DocPreview } from '@/types'
import { deleteDoc, getDocPreview, reparseDoc } from '@/api/docs'

const route = useRoute()
const router = useRouter()

const loading = ref(true)
const preview = ref<DocPreview | null>(null)
const activeTab = ref('body')
let pollTimer: ReturnType<typeof setInterval> | null = null

const docId = computed(() => String(route.params.id || ''))

const isProcessing = computed(() => {
  const s = preview.value?.status
  return (
    !!s &&
    ['uploaded', 'queued', 'parsing', 'normalizing', 'chunking', 'indexing'].includes(s)
  )
})

const metaLine = computed(() => {
  const m = preview.value?.meta
  if (!m) return ''
  const parts: string[] = []
  if (m.page_count != null) parts.push(`${m.page_count} 页`)
  if (m.chunk_count != null) parts.push(`${m.chunk_count} chunks`)
  if (m.duration_sec != null) parts.push(`耗时 ${m.duration_sec}s`)
  if (m.engine) parts.push(m.engine)
  return parts.join(' · ')
})

const htmlBody = computed(() => {
  const md = preview.value?.markdown || ''
  if (!md) return ''
  try {
    return marked.parse(md, { async: false }) as string
  } catch {
    return `<pre>${escapeHtml(md)}</pre>`
  }
})

function escapeHtml(s: string) {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

function statusTagType(status?: string) {
  if (status === 'ready') return 'success'
  if (status === 'failed' || status === 'needs_ocr') return 'danger'
  if (status === 'queued' || status === 'uploaded') return 'info'
  return 'warning'
}

async function load() {
  if (!docId.value) return
  loading.value = true
  try {
    const { data } = await getDocPreview(docId.value)
    preview.value = data
  } catch (e: any) {
    ElMessage.error(e.message || '加载失败')
    preview.value = null
  } finally {
    loading.value = false
  }
}

function syncPoll() {
  if (isProcessing.value) {
    if (!pollTimer) {
      pollTimer = setInterval(load, 2500)
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

function goBack() {
  router.push({ name: 'docs' })
}

function scrollToBlock(blockId: string) {
  activeTab.value = 'body'
  requestAnimationFrame(() => {
    const el = document.getElementById(`block-${blockId}`)
    el?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  })
}

async function onReparse() {
  try {
    await ElMessageBox.confirm(
      '将清除旧索引并按当前文件重新解析，是否继续？',
      '重新解析',
      { type: 'warning' },
    )
    const { data } = await reparseDoc(docId.value)
    ElMessage.success(data.message)
    await loadAndPoll()
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error(e.message || '操作失败')
  }
}

async function onDelete() {
  try {
    await ElMessageBox.confirm(
      '删除后将同时移除本地文件与检索索引，且不可恢复。',
      '删除确认',
      { type: 'warning' },
    )
    const { data } = await deleteDoc(docId.value)
    ElMessage.success(data.message)
    goBack()
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error(e.message || '删除失败')
  }
}

function goChat() {
  router.push({ name: 'chat' })
}

watch(docId, () => loadAndPoll())
watch(isProcessing, syncPoll)

onMounted(loadAndPoll)
onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<template>
  <div class="page-card preview-page" v-loading="loading && !preview">
    <div class="preview-top">
      <div class="preview-top-left">
        <el-button text @click="goBack">← 知识库</el-button>
        <h2 class="preview-title">
          {{ preview?.meta?.filename || preview?.meta?.title || '文档预览' }}
        </h2>
        <el-tag
          v-if="preview"
          size="small"
          :type="statusTagType(preview.status)"
        >
          {{ preview.stage_label || preview.status }}
        </el-tag>
      </div>
      <div class="preview-top-right" v-if="preview">
        <el-button v-if="preview.ready" type="primary" plain @click="goChat">
          去智能问答
        </el-button>
        <el-button @click="onReparse">重新解析</el-button>
        <el-button type="danger" plain @click="onDelete">删除</el-button>
      </div>
    </div>

    <p v-if="metaLine" class="meta-line">{{ metaLine }}</p>

    <!-- 处理中 -->
    <div v-if="preview && isProcessing" class="state-panel">
      <div class="state-title">文档仍在处理中</div>
      <p class="state-desc">
        当前阶段：{{ preview.stage_label || preview.status }}。列表与本页会自动刷新，完成后可查看结构预览。
      </p>
      <el-button @click="goBack">返回列表</el-button>
    </div>

    <!-- 失败 -->
    <div v-else-if="preview && preview.status === 'failed'" class="state-panel state-fail">
      <div class="state-title">解析失败</div>
      <p class="state-desc">
        {{ preview.message || preview.meta?.error || '请更换文件或重试' }}
      </p>
      <div class="state-actions">
        <el-button type="primary" @click="onReparse">重新解析</el-button>
        <el-button @click="goBack">返回列表</el-button>
      </div>
    </div>

    <!-- 就绪预览 -->
    <div v-else-if="preview && preview.ready" class="preview-body">
      <aside class="outline-pane">
        <div class="pane-label">大纲</div>
        <ul v-if="preview.outline?.length" class="outline-list">
          <li
            v-for="item in preview.outline"
            :key="item.block_id"
            :style="{ paddingLeft: `${(item.level - 1) * 12 + 4}px` }"
          >
            <button type="button" class="outline-btn" @click="scrollToBlock(item.block_id)">
              {{ item.text }}
            </button>
          </li>
        </ul>
        <p v-else class="empty-hint">暂无标题层级</p>
      </aside>

      <section class="content-pane">
        <el-tabs v-model="activeTab">
          <el-tab-pane label="结构化正文" name="body">
            <div class="md-body" v-html="htmlBody" />
          </el-tab-pane>
          <el-tab-pane :label="`表格 (${preview.tables?.length || 0})`" name="tables">
            <div v-if="!preview.tables?.length" class="empty-hint">
              本文档未识别到表格块
            </div>
            <div
              v-for="(t, idx) in preview.tables"
              :key="t.block_id"
              class="table-card"
            >
              <div class="table-meta">
                <span>表 {{ idx + 1 }}</span>
                <el-tag v-if="t.merged" size="small" type="warning">跨页已合并</el-tag>
                <span v-if="t.section_path?.length" class="path">
                  {{ t.section_path.join(' > ') }}
                </span>
                <span v-if="t.page_start" class="path">
                  页 {{ t.page_start }}<template v-if="t.page_end && t.page_end !== t.page_start">–{{ t.page_end }}</template>
                </span>
              </div>
              <div class="table-html" v-html="t.html || ''" />
            </div>
          </el-tab-pane>
          <el-tab-pane label="详情" name="info">
            <dl class="info-dl">
              <dt>文档 ID</dt>
              <dd>{{ preview.id }}</dd>
              <dt>引擎</dt>
              <dd>{{ preview.meta?.engine || '—' }}</dd>
              <dt>块数量</dt>
              <dd>{{ preview.ir_summary?.block_count ?? '—' }}</dd>
              <dt>上传时间</dt>
              <dd>{{ preview.meta?.created_at || '—' }}</dd>
              <dt>更新时间</dt>
              <dd>{{ preview.meta?.updated_at || '—' }}</dd>
            </dl>
          </el-tab-pane>
        </el-tabs>
      </section>
    </div>

    <div v-else-if="!loading" class="state-panel">
      <div class="state-title">无法加载文档</div>
      <el-button @click="goBack">返回列表</el-button>
    </div>
  </div>
</template>

<style scoped>
.preview-top {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 4px;
}

.preview-top-left {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.preview-title {
  margin: 0;
  font-size: 1.1rem;
  font-weight: 700;
  max-width: 28rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.preview-top-right {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.meta-line {
  margin: 0 0 14px;
  font-size: 13px;
  color: var(--muted);
}

.state-panel {
  padding: 48px 20px;
  text-align: center;
}

.state-title {
  font-size: 1.05rem;
  font-weight: 600;
  margin-bottom: 8px;
}

.state-desc {
  color: var(--muted);
  font-size: 14px;
  max-width: 36rem;
  margin: 0 auto 16px;
  line-height: 1.6;
}

.state-actions {
  display: flex;
  gap: 8px;
  justify-content: center;
}

.preview-body {
  display: grid;
  grid-template-columns: minmax(160px, 240px) 1fr;
  gap: 16px;
  min-height: 480px;
  border-top: 1px solid var(--border);
  padding-top: 12px;
}

@media (max-width: 800px) {
  .preview-body {
    grid-template-columns: 1fr;
  }
}

.outline-pane {
  border-right: 1px solid var(--border);
  padding-right: 12px;
  max-height: calc(100vh - 220px);
  overflow-y: auto;
}

@media (max-width: 800px) {
  .outline-pane {
    border-right: none;
    border-bottom: 1px solid var(--border);
    padding-right: 0;
    padding-bottom: 12px;
    max-height: 180px;
  }
}

.pane-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--muted);
  margin-bottom: 8px;
}

.outline-list {
  list-style: none;
  margin: 0;
  padding: 0;
}

.outline-btn {
  display: block;
  width: 100%;
  text-align: left;
  border: none;
  background: transparent;
  color: var(--text);
  font-size: 13px;
  line-height: 1.45;
  padding: 6px 4px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.15s ease;
}

.outline-btn:hover {
  background: var(--user-bg);
  color: var(--primary);
}

.content-pane {
  min-width: 0;
  max-height: calc(100vh - 220px);
  overflow-y: auto;
}

.md-body {
  font-size: 14px;
  line-height: 1.7;
  color: var(--text);
  max-width: 75ch;
}

.md-body :deep(h1),
.md-body :deep(h2),
.md-body :deep(h3),
.md-body :deep(h4) {
  margin: 1.2em 0 0.5em;
  line-height: 1.35;
  text-wrap: balance;
  scroll-margin-top: 12px;
}

.md-body :deep(table) {
  border-collapse: collapse;
  width: 100%;
  margin: 12px 0;
  font-size: 13px;
}

.md-body :deep(th),
.md-body :deep(td),
.table-html :deep(th),
.table-html :deep(td) {
  border: 1px solid var(--border);
  padding: 6px 8px;
  text-align: left;
}

.md-body :deep(th),
.table-html :deep(th) {
  background: #f8fafc;
  font-weight: 600;
}

.table-card {
  margin-bottom: 20px;
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 12px;
  background: #fafbfc;
}

.table-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
  font-size: 13px;
  font-weight: 600;
}

.table-meta .path {
  font-weight: 400;
  color: var(--muted);
  font-size: 12px;
}

.table-html {
  overflow-x: auto;
  background: #fff;
  border-radius: 6px;
}

.table-html :deep(table) {
  border-collapse: collapse;
  width: 100%;
  font-size: 13px;
}

.empty-hint {
  color: var(--muted);
  font-size: 13px;
  padding: 12px 0;
}

.info-dl {
  display: grid;
  grid-template-columns: 100px 1fr;
  gap: 8px 12px;
  font-size: 13px;
  margin: 0;
}

.info-dl dt {
  color: var(--muted);
}

.info-dl dd {
  margin: 0;
  word-break: break-all;
}
</style>
