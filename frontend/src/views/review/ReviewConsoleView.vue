<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Check,
  Close,
  Download,
  View,
} from '@element-plus/icons-vue'
import RiskCard from '@/components/review/RiskCard.vue'
import ReviewAssistant from '@/components/review/ReviewAssistant.vue'
import ReviewFooter from '@/components/review/ReviewFooter.vue'
import ReviewPdfPreview from '@/components/review/ReviewPdfPreview.vue'
import ReviewStepper from '@/components/review/ReviewStepper.vue'
import { useReviewStore } from '@/stores/review'
import { downloadExportArtifact } from '@/api/review'
import type { ReviewHighlightRect, ReviewRisk } from '@/types'

const review = useReviewStore()
const router = useRouter()
const route = useRoute()
const activeAnalysisTab = ref<'findings' | 'assistant'>('findings')
const loading = ref(false)
const loadError = ref('')
const exporting = ref(false)
const exportError = ref('')
const decidingFindingId = ref('')
const decideError = ref('')
const narrowMode = ref(false)
const narrowPane = ref<'preview' | 'detail'>('preview')
let narrowQuery: MediaQueryList | null = null

const hasJob = computed(() => Boolean(review.analysisJobId))
const selectedRisk = computed(
  () => review.risks.find((risk) => risk.id === review.activeFindingId) ?? null,
)
const findingCount = computed(() => review.risks.length)
const overallRisk = computed(() => {
  if (!review.risks.length) return '无'
  if (review.risks.some((risk) => risk.level === 'high')) return '高'
  if (review.risks.some((risk) => risk.level === 'medium')) return '中'
  return '低'
})
const documentLabel = computed(() => {
  const names = review.files.filter((file) => file.status !== 'failed').map((file) => file.name)
  return names.length ? names.join('、') : '尚未关联待审文档'
})
const analysisInProgress = computed(() =>
  ['loading', 'queued', 'parsing', 'running'].includes(review.analysisStatus),
)
const severityMeta = computed(() => {
  const level = selectedRisk.value?.level ?? 'low'
  if (level === 'high') return { label: '高风险', type: 'danger' as const }
  if (level === 'medium') return { label: '中风险', type: 'warning' as const }
  return { label: '低风险', type: 'info' as const }
})

/** PDF 预览加载哪个文档：优先选中 finding 的文档，其次批次中第一个文档 */
const pdfDocId = computed(() => {
  if (selectedRisk.value?.documentId) return selectedRisk.value.documentId
  return review.files.find((file) => file.documentId)?.documentId ?? ''
})
const activePage = computed(() => {
  const evidence = selectedRisk.value?.evidence
  if (!evidence) return null
  return evidencePage(evidence)
})
const highlightRects = computed<ReviewHighlightRect[]>(() => {
  const evidence = selectedRisk.value?.evidence
  if (!evidence) return []
  return evidenceRects(evidence)
})

onMounted(() => {
  review.goToStep(Number(route.meta.reviewStep) || 4)
  // 支持 deep-link：/review/console?jobId=xxx 直接加载指定审查任务（刷新页面后也可恢复）
  const jobId = typeof route.query.jobId === 'string' ? route.query.jobId : ''
  if (jobId && jobId !== review.analysisJobId) review.analysisJobId = jobId
  if (review.analysisJobId) void loadResults()
  if (typeof window !== 'undefined' && typeof window.matchMedia === 'function') {
    narrowQuery = window.matchMedia('(max-width: 1199px)')
    narrowMode.value = narrowQuery.matches
    narrowQuery.addEventListener('change', onNarrowChange)
  }
})

onBeforeUnmount(() => {
  if (narrowQuery) narrowQuery.removeEventListener('change', onNarrowChange)
})

function onNarrowChange(event: MediaQueryListEvent) {
  narrowMode.value = event.matches
}

async function loadResults() {
  loading.value = true
  loadError.value = ''
  try {
    await review.refreshJob()
    await review.loadFindings()
  } catch (err) {
    loadError.value = err instanceof Error ? err.message : '审查结果加载失败'
  } finally {
    loading.value = false
  }
}

/** 点击问题卡片：选中（跳到证据页 + 高亮）；再点同一问题取消选中 */
function toggleRisk(id: string) {
  if (review.activeFindingId === id) {
    review.activeFindingId = null
    activeAnalysisTab.value = 'findings'
    return
  }
  selectRisk(id)
}

function selectRisk(id: string) {
  review.activeFindingId = id
  const risk = review.risks.find((item) => item.id === id)
  if (risk?.evidence) locateCitation(risk.evidence)
}

/** 「定位证据」按钮：总是选中并跳到证据位置 */
function locateRisk(risk: ReviewRisk) {
  activeAnalysisTab.value = 'findings'
  selectRisk(risk.id)
}

function locateCitation(anchor: Record<string, unknown>) {
  activeAnalysisTab.value = 'findings'
  window.dispatchEvent(new CustomEvent('review:locate-evidence', { detail: anchor }))
}

/** evidence_anchor → 预览高亮矩形列表（无 rect / precision=page 时退化为页级标记） */
function evidenceRects(anchor: Record<string, unknown>): ReviewHighlightRect[] {
  const page = evidencePage(anchor)
  const precision = anchor.precision
  const rawRects = Array.isArray(anchor.rects) ? anchor.rects : []
  const space = String(anchor.coordinate_space || 'pdf-pt')
  if (precision === 'page' || rawRects.length === 0) {
    return [{ page, x0: 0, y0: 0, x1: 0, y1: 0, space, pageLevel: true }]
  }
  return rawRects.map((rect: Record<string, unknown>) => ({
    page: Math.max(1, Math.round(Number(rect.page) || page)),
    x0: Number(rect.x0) || 0,
    y0: Number(rect.y0) || 0,
    x1: Number(rect.x1) || 0,
    y1: Number(rect.y1) || 0,
    space: String(rect.space || space),
  }))
}

function evidencePage(anchor: Record<string, unknown>) {
  const page = Number(anchor.page_number)
  return Number.isFinite(page) && page > 0 ? Math.round(page) : 1
}

function evidencePrecisionLabel(anchor: Record<string, unknown>) {
  return anchor.precision === 'page' ? '页级定位' : '精确定位'
}

async function decideRisk(decision: 'accepted' | 'dismissed') {
  const risk = selectedRisk.value
  if (!risk || decidingFindingId.value) return
  decidingFindingId.value = risk.id
  decideError.value = ''
  try {
    await review.decideRisk(risk.id, decision, '')
  } catch (err) {
    decideError.value = err instanceof Error ? err.message : '处置提交失败'
  } finally {
    decidingFindingId.value = ''
  }
}

function approveDraft() {
  review.approveDraft()
}

function rejectChanges() {
  review.rejectChanges()
}

async function exportReport() {
  if (!review.analysisJobId || exporting.value) return
  exporting.value = true
  exportError.value = ''
  try {
    const { data: artifact } = await review.exportReport()
    await downloadExportArtifact(artifact.id, artifact.filename || `review-${review.analysisJobId}.md`)
  } catch (err) {
    exportError.value = err instanceof Error ? err.message : '报告导出失败'
  } finally {
    exporting.value = false
  }
}

async function goPrevious() {
  review.previousStep()
  await router.push({ name: 'review-rules' })
}

function goToUpload() {
  review.goToStep(1)
  void router.push({ name: 'review-upload' })
}
</script>

<template>
  <div class="console-page">
    <ReviewStepper :current="review.currentStep" />

    <div class="console-header">
      <div>
        <h1>AI 审查分析</h1>
        <p>{{ documentLabel }}</p>
      </div>
    </div>

    <div v-if="!hasJob" class="console-empty">
      <h2>尚未开始审查</h2>
      <p>请先返回第一步上传待审文档并启动分析，审查结果将在此处展示。</p>
      <el-button data-test="back-to-upload" type="primary" @click="goToUpload">返回文档上传</el-button>
    </div>

    <template v-else>
      <div class="console-layout" :class="{ 'console-layout--narrow': narrowMode }">
        <!-- 左：审查发现列表 -->
        <aside class="findings-panel" aria-label="审查发现列表">
          <div class="findings-heading">
            <h2>审查结果</h2>
          </div>
          <div class="analysis-tabs" role="tablist" aria-label="审查分析视图">
            <button
              id="findings-tab"
              type="button"
              role="tab"
              data-test="findings-tab"
              :aria-selected="activeAnalysisTab === 'findings'"
              aria-controls="findings-panel-content"
              :class="{ 'analysis-tab--active': activeAnalysisTab === 'findings' }"
              @click="activeAnalysisTab = 'findings'"
            >审查发现</button>
            <button
              id="assistant-tab"
              type="button"
              role="tab"
              data-test="assistant-tab"
              :aria-selected="activeAnalysisTab === 'assistant'"
              aria-controls="assistant-panel-content"
              :class="{ 'analysis-tab--active': activeAnalysisTab === 'assistant' }"
              @click="activeAnalysisTab = 'assistant'"
            >问答助手</button>
          </div>

          <div
            v-if="activeAnalysisTab === 'findings'"
            id="findings-panel-content"
            class="findings-content"
            role="tabpanel"
            aria-labelledby="findings-tab"
          >
            <div class="metrics-grid">
              <div><span>发现问题</span><strong>{{ findingCount }}</strong></div>
              <div><span>风险评分</span><strong class="risk-score">{{ overallRisk }}</strong></div>
            </div>
            <div class="findings-section">
              <div class="findings-section__title"><h3>审查发现</h3><span>{{ findingCount }} 项</span></div>
              <div class="risk-list">
                <div
                  v-for="risk in review.risks"
                  :key="risk.id"
                  class="risk-item"
                  :class="{ 'risk-item--active': review.activeFindingId === risk.id }"
                >
                  <RiskCard
                    :risk="risk"
                    :action="risk.action ?? 'pending'"
                    :selected="review.activeFindingId === risk.id"
                    @select="toggleRisk"
                  />
                  <button
                    type="button"
                    class="risk-locate"
                    data-test="locate-evidence"
                    :aria-label="`定位证据：${risk.title}`"
                    @click="locateRisk(risk)"
                  >
                    <el-icon aria-hidden="true"><View /></el-icon>
                    定位证据
                  </button>
                </div>
              </div>
              <div v-if="loadError" class="findings-empty findings-empty--error" role="alert">{{ loadError }}</div>
              <div v-else-if="loading && !review.risks.length" class="findings-empty">正在加载审查结果…</div>
              <div v-else-if="!review.risks.length" class="findings-empty">暂无审查发现</div>
            </div>
            <p v-if="exportError" class="console-error" role="alert">{{ exportError }}</p>
            <div class="console-actions">
              <el-button type="danger" plain :disabled="review.analysisStatus !== 'complete' && review.analysisStatus !== 'complete_degraded'" @click="rejectChanges">拒绝更改</el-button>
              <el-button
                data-test="approve-draft"
                type="primary"
                :disabled="review.analysisStatus !== 'complete' && review.analysisStatus !== 'complete_degraded'"
                @click="approveDraft"
              >批准草案</el-button>
              <el-button data-test="export-report" plain :loading="exporting" @click="exportReport">
                <el-icon aria-hidden="true"><Download /></el-icon>
                导出详细报告
              </el-button>
            </div>
          </div>
          <div v-else id="assistant-panel-content" role="tabpanel" aria-labelledby="assistant-tab">
            <ReviewAssistant :risk="selectedRisk ?? undefined" @locate="locateCitation" />
          </div>
        </aside>

        <!-- 窄屏切换：预览 / 详情 -->
        <div v-if="narrowMode" class="narrow-switch" role="tablist" aria-label="预览与详情切换">
          <button
            type="button"
            role="tab"
            data-test="narrow-preview-tab"
            :aria-selected="narrowPane === 'preview'"
            :class="{ 'narrow-switch__active': narrowPane === 'preview' }"
            @click="narrowPane = 'preview'"
          >PDF 预览</button>
          <button
            type="button"
            role="tab"
            data-test="narrow-detail-tab"
            :aria-selected="narrowPane === 'detail'"
            :class="{ 'narrow-switch__active': narrowPane === 'detail' }"
            @click="narrowPane = 'detail'"
          >问题详情</button>
        </div>

        <!-- 中：PDF 预览 + 证据高亮 -->
        <main class="reader-panel" :class="{ 'pane-hidden': narrowMode && narrowPane !== 'preview' }">
          <ReviewPdfPreview
            :doc-id="pdfDocId"
            :highlight-rects="highlightRects"
            :active-page="activePage"
            :scale="100"
          />
        </main>

        <!-- 右：问题详情 -->
        <aside class="detail-panel" :class="{ 'pane-hidden': narrowMode && narrowPane !== 'detail' }" aria-label="问题详情">
          <template v-if="selectedRisk">
            <header class="detail-header">
              <el-tag :type="severityMeta.type" size="small" effect="dark">{{ severityMeta.label }}</el-tag>
              <h2 data-test="detail-title">{{ selectedRisk.title }}</h2>
              <p class="detail-section">{{ selectedRisk.section }}</p>
            </header>

            <div class="detail-body">
              <div class="detail-block" data-test="detail-quote">
                <h3>原文引用</h3>
                <blockquote>{{ selectedRisk.quote || selectedRisk.currentText || '（未提供原文引用）' }}</blockquote>
              </div>
              <div class="detail-block" data-test="detail-reason">
                <h3>风险原因</h3>
                <p>{{ selectedRisk.description }}</p>
              </div>
              <div class="detail-block" data-test="detail-suggestion">
                <h3>修改建议</h3>
                <p>{{ selectedRisk.suggestion || '（暂无修改建议）' }}</p>
              </div>
              <div v-if="selectedRisk.evidence" class="detail-block detail-block--evidence" data-test="detail-evidence">
                <h3>证据定位</h3>
                <p>第 {{ evidencePage(selectedRisk.evidence) }} 页 · {{ evidencePrecisionLabel(selectedRisk.evidence) }}</p>
                <el-button size="small" type="primary" plain data-test="detail-locate" @click="locateRisk(selectedRisk)">
                  <el-icon aria-hidden="true"><View /></el-icon>
                  定位证据
                </el-button>
              </div>
            </div>

            <p v-if="decideError" class="detail-error" role="alert">{{ decideError }}</p>

            <footer class="detail-actions">
              <el-button
                data-test="decide-accept"
                :type="selectedRisk.action === 'accepted' ? 'success' : 'primary'"
                :plain="selectedRisk.action !== 'accepted'"
                :loading="decidingFindingId === selectedRisk.id"
                @click="decideRisk('accepted')"
              >
                <el-icon aria-hidden="true"><Check /></el-icon>
                {{ selectedRisk.action === 'accepted' ? '已采纳建议' : '采纳建议' }}
              </el-button>
              <el-button
                data-test="decide-dismiss"
                :type="selectedRisk.action === 'dismissed' ? 'info' : 'default'"
                :loading="decidingFindingId === selectedRisk.id"
                @click="decideRisk('dismissed')"
              >
                <el-icon aria-hidden="true"><Close /></el-icon>
                {{ selectedRisk.action === 'dismissed' ? '已忽略风险' : '忽略风险' }}
              </el-button>
            </footer>
          </template>

          <div v-else class="detail-empty" data-test="detail-empty">
            <el-icon aria-hidden="true"><View /></el-icon>
            <p>点击左侧发现查看详情，或使用「定位证据」跳到原文对应位置。</p>
          </div>
        </aside>
      </div>

      <ReviewFooter previous-label="返回规则设置" next-label="分析完成" :next-disabled="true" @previous="goPrevious">
        <span v-if="review.analysisStatus === 'failed'">{{ review.error || '分析失败，请返回重试。' }}</span>
        <span v-else-if="analysisInProgress">审查分析进行中，请稍候…</span>
        <span v-else>分析完成，共发现 {{ findingCount }} 项风险。</span>
      </ReviewFooter>
    </template>
  </div>
</template>

<style scoped>
.console-page {
  width: min(1600px, 100%);
  margin: 0 auto;
}

.console-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
  margin-bottom: 20px;
}

.console-header h1 {
  margin: 0 0 5px;
  font-size: 34px;
}

.console-header p {
  margin: 0;
  color: var(--ink-muted);
  font-size: 12px;
}

.console-empty {
  display: grid;
  min-height: 420px;
  place-items: center;
  align-content: center;
  gap: 12px;
  padding: 48px 24px;
  border: 1px solid var(--outline-soft);
  border-radius: var(--radius-md);
  background: var(--surface);
  text-align: center;
}

.console-empty h2 {
  margin: 0;
  font-size: 24px;
}

.console-empty p {
  max-width: 460px;
  margin: 0 0 12px;
  color: var(--ink-muted);
  font-size: 14px;
  line-height: 1.7;
}

/* 三栏布局：发现列表 | PDF 预览 | 问题详情 */
.console-layout {
  display: grid;
  grid-template-columns: 300px minmax(0, 1fr) 320px;
  min-height: 680px;
  border: 1px solid var(--outline-soft);
  background: var(--surface);
}

.findings-panel {
  display: flex;
  min-width: 0;
  min-height: 0;
  flex-direction: column;
  border-right: 1px solid var(--outline-soft);
  background: var(--surface);
}

.reader-panel {
  display: flex;
  min-width: 0;
  min-height: 0;
  flex-direction: column;
  overflow: hidden;
  background: #eef2f8;
}

.detail-panel {
  display: flex;
  min-width: 0;
  min-height: 0;
  flex-direction: column;
  overflow-y: auto;
  border-left: 1px solid var(--outline-soft);
  background: var(--surface);
}

.narrow-switch {
  display: none;
}

.pane-hidden {
  display: none;
}

.analysis-tabs {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  padding: 0 20px;
  border-bottom: 1px solid var(--outline-soft);
}

.analysis-tabs button {
  min-height: var(--control-height);
  padding: 0 8px;
  border: 0;
  border-bottom: 2px solid transparent;
  color: var(--ink-muted);
  background: transparent;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
}

.analysis-tabs button:hover,
.analysis-tabs .analysis-tab--active {
  color: var(--action);
}

.analysis-tabs .analysis-tab--active {
  border-bottom-color: var(--action);
}

.findings-content {
  display: flex;
  min-height: 0;
  flex: 1;
  flex-direction: column;
  overflow-y: auto;
}

.findings-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 24px 20px 18px;
  border-bottom: 1px solid var(--outline-soft);
}

.findings-heading h2 {
  margin: 0;
  font-size: 20px;
}

.metrics-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  padding: 16px 20px;
  border-bottom: 1px solid var(--outline-soft);
}

.metrics-grid > div {
  display: grid;
  gap: 7px;
  padding: 13px;
  border: 1px solid var(--outline-soft);
  border-radius: var(--radius-sm);
  background: var(--surface-low);
}

.metrics-grid span {
  color: var(--ink-muted);
  font-size: 11px;
}

.metrics-grid strong {
  font-size: 24px;
}

.metrics-grid .risk-score {
  color: var(--danger);
}

.findings-section {
  display: grid;
  min-height: 0;
  gap: 12px;
  padding: 20px;
}

.findings-section__title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.findings-section__title h3 {
  margin: 0;
  font-size: 15px;
}

.findings-section__title span {
  color: var(--ink-muted);
  font-size: 10px;
}

.risk-list {
  display: grid;
  gap: 12px;
}

.risk-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.risk-locate {
  display: inline-flex;
  align-items: center;
  align-self: flex-end;
  gap: 5px;
  min-height: 26px;
  padding: 3px 10px;
  border: 1px solid var(--outline-soft);
  border-radius: var(--radius-sm);
  color: var(--action);
  background: var(--surface);
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
}

.risk-locate:hover {
  border-color: var(--action);
  background: var(--action-soft);
}

.risk-item--active .risk-locate {
  border-color: var(--action-outline);
}

.findings-empty {
  padding: 20px 12px;
  border: 1px dashed var(--outline);
  border-radius: var(--radius-sm);
  color: var(--ink-muted);
  background: var(--surface-low);
  font-size: 12px;
  text-align: center;
}

.findings-empty--error {
  border-color: var(--danger-outline);
  color: var(--danger);
  background: var(--danger-soft);
}

.console-error {
  margin: 0 20px 12px;
  color: var(--danger);
  font-size: 11px;
}

.console-actions {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin-top: auto;
  padding: 16px 20px 20px;
  border-top: 1px solid var(--outline-soft);
}

.console-actions .el-button {
  width: 100%;
  margin: 0;
}

.console-actions .el-button:last-child {
  grid-column: 1 / -1;
}

/* 问题详情 */
.detail-header {
  padding: 20px;
  border-bottom: 1px solid var(--outline-soft);
  background: var(--surface-low);
}

.detail-header h2 {
  margin: 12px 0 6px;
  font-size: 17px;
  line-height: 1.45;
}

.detail-section {
  margin: 0;
  color: var(--ink-muted);
  font-size: 11px;
}

.detail-body {
  display: grid;
  gap: 16px;
  padding: 20px;
}

.detail-block h3 {
  margin: 0 0 8px;
  color: var(--ink-muted);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.04em;
}

.detail-block p {
  margin: 0;
  color: var(--ink);
  font-size: 12px;
  line-height: 1.7;
}

.detail-block blockquote {
  margin: 0;
  padding: 10px 12px;
  border-left: 3px solid var(--action);
  border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
  color: var(--ink);
  background: var(--surface-low);
  font-size: 12px;
  line-height: 1.7;
}

.detail-block--evidence {
  padding: 12px;
  border: 1px solid var(--action-outline);
  border-radius: var(--radius-sm);
  background: var(--action-subtle);
}

.detail-block--evidence .el-button {
  margin-top: 8px;
}

.detail-error {
  margin: 0 20px 12px;
  color: var(--danger);
  font-size: 11px;
}

.detail-actions {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin-top: auto;
  padding: 16px 20px 20px;
  border-top: 1px solid var(--outline-soft);
}

.detail-actions .el-button {
  width: 100%;
  margin: 0;
}

.detail-empty {
  display: grid;
  min-height: 360px;
  place-items: center;
  align-content: center;
  gap: 10px;
  padding: 24px;
  color: var(--ink-muted);
  text-align: center;
}

.detail-empty .el-icon {
  font-size: 30px;
  color: var(--outline);
}

.detail-empty p {
  max-width: 220px;
  margin: 0;
  font-size: 12px;
  line-height: 1.7;
}

@media (max-width: 1199px) {
  .console-layout {
    grid-template-columns: 1fr;
  }

  .findings-panel {
    border-right: 0;
    border-bottom: 1px solid var(--outline-soft);
  }

  .reader-panel,
  .detail-panel {
    min-height: 480px;
    border-left: 0;
  }

  .console-layout--narrow .narrow-switch {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    border-bottom: 1px solid var(--outline-soft);
  }

  .narrow-switch button {
    min-height: 44px;
    border: 0;
    border-bottom: 2px solid transparent;
    color: var(--ink-muted);
    background: var(--surface);
    font-size: 13px;
    font-weight: 700;
    cursor: pointer;
  }

  .narrow-switch .narrow-switch__active {
    border-bottom-color: var(--action);
    color: var(--action);
  }
}

@media (max-width: 680px) {
  .console-header h1 {
    font-size: 28px;
  }

  .console-header {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
