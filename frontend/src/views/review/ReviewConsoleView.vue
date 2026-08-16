<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Check,
  Close,
  Download,
} from '@element-plus/icons-vue'
import RiskCard from '@/components/review/RiskCard.vue'
import ReviewConfigPanel from '@/components/review/ReviewConfigPanel.vue'
import ReviewAssistant from '@/components/review/ReviewAssistant.vue'
import ReviewPdfPreview from '@/components/review/ReviewPdfPreview.vue'
import { useReviewStore } from '@/stores/review'
import { downloadExportArtifact, type ReviewCitation } from '@/api/review'
import type { ReviewHighlightRect, ReviewRisk } from '@/types'

const review = useReviewStore()
const router = useRouter()
const route = useRoute()
const activeAnalysisTab = ref<'findings' | 'assistant' | 'config'>('findings')
const loading = ref(false)
const loadError = ref('')
const exporting = ref(false)
const exportError = ref('')
const decidingFindingId = ref('')
const decideError = ref('')

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
/** 全部发现所在页：缩略图风险点标记（不依赖选中） */
const findingRiskPages = computed(() =>
  review.risks
    .map((risk) => Number((risk.evidence as Record<string, unknown> | undefined)?.page_number))
    .filter((page) => Number.isFinite(page) && page > 0)
    .map((page) => Math.round(page)),
)

onMounted(() => {
  review.goToStep(Number(route.meta.reviewStep) || 4)
  // 集成页：加载范本、规则、已保存配置并恢复最近批次
  void review.initialize()
  // 支持 deep-link：/review/console?jobId=xxx 直接加载指定审查任务（刷新页面后也可恢复）
  const jobId = typeof route.query.jobId === 'string' ? route.query.jobId : ''
  if (jobId && jobId !== review.analysisJobId) review.analysisJobId = jobId
  if (review.analysisJobId) void loadResults()
  else activeAnalysisTab.value = 'config'
})

/** 配置面板启动分析完成：切回审查发现并刷新结果 */
function onAnalysisStarted() {
  activeAnalysisTab.value = 'findings'
  void loadResults()
}

async function loadResults() {
  loading.value = true
  loadError.value = ''
  try {
    await review.loadBatchFiles()
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

/** 「定位证据」：总是选中并跳到证据位置 */
function locateRisk(risk: ReviewRisk) {
  activeAnalysisTab.value = 'findings'
  selectRisk(risk.id)
}

function locateCitation(anchor: ReviewCitation | Record<string, unknown>) {
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

async function decideRisk(risk: ReviewRisk, decision: 'accepted' | 'dismissed') {
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

function goToUpload() {
  review.goToStep(1)
  void router.push({ name: 'review-upload' })
}
</script>

<template>
  <div class="console-page">
    <div class="console-header">
      <div>
        <h1>AI 审查分析</h1>
        <p>{{ documentLabel }}</p>
      </div>
    </div>

    <div class="console-layout">
        <!-- 左：PDF 文档预览（缩略图栏 + 可缩放画布 + 证据高亮） -->
        <main class="reader-panel" aria-label="PDF 文档预览">
          <div v-if="!pdfDocId" class="reader-placeholder" data-test="reader-placeholder">
            <p>尚未加载待审文档</p>
            <span>上传文档并启动分析后，这里将展示 PDF 预览与证据高亮。</span>
          </div>
          <ReviewPdfPreview
            v-else
            :doc-id="pdfDocId"
            :filename="documentLabel"
            :highlight-rects="highlightRects"
            :risk-pages="findingRiskPages"
            :active-page="activePage"
            :scale="100"
          />
        </main>

        <!-- 右：审查结果（风险卡内联修改建议） + 问答助手 -->
        <aside class="findings-panel" aria-label="审查结果">
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
            <button
              id="config-tab"
              type="button"
              role="tab"
              data-test="config-tab"
              :aria-selected="activeAnalysisTab === 'config'"
              aria-controls="config-panel-content"
              :class="{ 'analysis-tab--active': activeAnalysisTab === 'config' }"
              @click="activeAnalysisTab = 'config'"
            >审查配置</button>
          </div>

          <div
            v-if="activeAnalysisTab === 'findings'"
            id="findings-panel-content"
            class="findings-content panel-content"
            role="tabpanel"
            aria-labelledby="findings-tab"
          >
            <div v-if="!hasJob" class="findings-empty findings-empty--guide">
              <p>尚未开始审查。</p>
              <p>请先在「审查配置」中选择范本、启用条款规则并启动全量分析；如未上传文档，请先前往上传。</p>
              <div class="findings-empty__actions">
                <el-button type="primary" @click="activeAnalysisTab = 'config'">前往审查配置</el-button>
                <el-button plain @click="goToUpload">文档上传</el-button>
              </div>
            </div>
            <div v-else class="metrics-grid">
              <div><span>发现问题</span><strong>{{ findingCount }}</strong></div>
              <div><span>风险评分</span><strong class="risk-score">{{ overallRisk }}</strong></div>
            </div>
            <div v-if="hasJob" class="findings-section">
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
                    @locate="locateRisk"
                    @decide="(decision) => decideRisk(risk, decision)"
                  />
                </div>
              </div>
              <div v-if="loadError" class="findings-empty findings-empty--error" role="alert">{{ loadError }}</div>
              <div v-else-if="loading && !review.risks.length" class="findings-empty">正在加载审查结果…</div>
              <div v-else-if="!review.risks.length" class="findings-empty">暂无审查发现</div>
            </div>
            <p v-if="hasJob && exportError" class="console-error" role="alert">{{ exportError }}</p>
            <p v-if="hasJob && decideError" class="console-error" role="alert">{{ decideError }}</p>
            <div v-if="hasJob" class="console-actions">
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
          <div v-else-if="activeAnalysisTab === 'assistant'" id="assistant-panel-content" class="panel-content" role="tabpanel" aria-labelledby="assistant-tab">
            <div v-if="!hasJob" class="findings-empty findings-empty--guide">
              <p>分析完成后，可围绕当前任务与所选风险进行文档问答。</p>
              <el-button type="primary" @click="activeAnalysisTab = 'config'">前往审查配置</el-button>
            </div>
            <ReviewAssistant v-else :risk="selectedRisk ?? undefined" @locate="locateCitation" />
          </div>
          <div v-else id="config-panel-content" class="panel-content" role="tabpanel" aria-labelledby="config-tab">
            <ReviewConfigPanel @started="onAnalysisStarted" />
          </div>
        </aside>
      </div>
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

.reader-placeholder {
  display: grid;
  min-height: 0;
  flex: 1;
  place-items: center;
  align-content: center;
  gap: 6px;
  color: var(--ink-muted);
  text-align: center;
}

.reader-placeholder p {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
}

.reader-placeholder span {
  max-width: 320px;
  font-size: 12px;
  line-height: 1.7;
}

.findings-empty--guide {
  display: grid;
  gap: 10px;
  margin: 16px 20px;
  padding: 20px;
  text-align: left;
}

.findings-empty--guide p {
  margin: 0;
  line-height: 1.7;
}

.findings-empty__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 4px;
}

/* 两栏布局：PDF 文档预览 | 审查结果（仿法智） */
.console-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 460px;
  height: calc(100vh - 280px);
  max-height: 900px;
  min-height: 480px;
  border: 1px solid var(--outline-soft);
  background: var(--surface);
}

.findings-panel {
  display: flex;
  min-width: 0;
  min-height: 0;
  flex-direction: column;
  border-left: 1px solid var(--outline-soft);
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

.analysis-tabs {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
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

.panel-content {
  display: flex;
  min-width: 0;
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
  border-radius: var(--radius-md);
  background: var(--surface-low);
}

.metrics-grid span {
  color: var(--ink-muted);
  font-size: 11px;
}

.metrics-grid strong {
  font-size: 22px;
}

.metrics-grid .risk-score {
  color: var(--danger);
}

.findings-section {
  display: flex;
  min-height: 0;
  flex: 1;
  flex-direction: column;
  padding: 16px 20px;
}

.findings-section__title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.findings-section__title h3 {
  margin: 0;
  font-size: 14px;
}

.findings-section__title span {
  color: var(--ink-muted);
  font-size: 11px;
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

.findings-empty {
  padding: 20px 12px;
  border: 1px dashed var(--outline-soft);
  border-radius: var(--radius-md);
  color: var(--ink-muted);
  text-align: center;
}

.findings-empty--error {
  border-color: var(--danger-outline);
  color: var(--danger);
}

.console-error {
  margin: 10px 20px 0;
  color: var(--danger);
  font-size: 12px;
}

.console-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  padding: 16px 20px;
  border-top: 1px solid var(--outline-soft);
  background: var(--surface);
}

@media (max-width: 1199px) {
  .console-layout {
    grid-template-columns: 1fr;
    height: auto;
    max-height: none;
    min-height: 560px;
  }

  .findings-panel {
    border-left: 0;
    border-top: 1px solid var(--outline-soft);
    min-height: 560px;
  }

  .reader-panel {
    min-height: 560px;
  }

  .console-header h1 {
    font-size: 26px;
  }

  .console-header {
    flex-direction: column;
    gap: 12px;
  }
}

@media (max-width: 680px) {
  .analysis-tabs {
    padding: 0 12px;
  }

  .findings-heading,
  .metrics-grid,
  .findings-section,
  .console-actions {
    padding-left: 12px;
    padding-right: 12px;
  }
}
</style>
