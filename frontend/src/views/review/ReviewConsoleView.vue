<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Download,
  MoreFilled,
  Printer,
  ZoomIn,
  ZoomOut,
} from '@element-plus/icons-vue'
import RiskCard from '@/components/review/RiskCard.vue'
import ReviewAssistant from '@/components/review/ReviewAssistant.vue'
import ReviewFooter from '@/components/review/ReviewFooter.vue'
import ReviewStepper from '@/components/review/ReviewStepper.vue'
import { useReviewStore } from '@/stores/review'
import { downloadExportArtifact } from '@/api/review'

const review = useReviewStore()
const router = useRouter()
const route = useRoute()
const selectedRiskId = ref('')
const zoom = ref(100)
const activeAnalysisTab = ref<'findings' | 'assistant'>('findings')
const loading = ref(false)
const loadError = ref('')
const exporting = ref(false)
const exportError = ref('')

const hasJob = computed(() => Boolean(review.analysisJobId))
const selectedRisk = computed(() => review.risks.find((risk) => risk.id === selectedRiskId.value))
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

onMounted(() => {
  review.goToStep(Number(route.meta.reviewStep) || 4)
  if (review.analysisJobId) void loadResults()
})

async function loadResults() {
  loading.value = true
  loadError.value = ''
  try {
    await review.refreshJob()
    await review.loadFindings()
    if (!selectedRiskId.value && review.risks[0]) selectedRiskId.value = review.risks[0].id
  } catch (err) {
    loadError.value = err instanceof Error ? err.message : '审查结果加载失败'
  } finally {
    loading.value = false
  }
}

function selectRisk(id: string) {
  selectedRiskId.value = id
  const risk = review.risks.find((item) => item.id === id)
  if (risk?.evidence) locateCitation(risk.evidence)
}

function locateCitation(anchor: Record<string, unknown>) {
  activeAnalysisTab.value = 'findings'
  window.dispatchEvent(new CustomEvent('review:locate-evidence', { detail: anchor }))
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

// 纯阅读缩放：仅调整正文显示比例，不参与证据定位。
function adjustZoom(amount: number) {
  zoom.value = Math.min(120, Math.max(80, zoom.value + amount))
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
      <div class="console-layout">
        <main class="reader-panel">
          <div class="reader-toolbar">
            <div class="reader-toolbar__title"><strong>文档正文</strong></div>
            <div class="reader-tools" aria-label="阅读工具">
              <button type="button" aria-label="缩小" @click="adjustZoom(-10)"><el-icon><ZoomOut /></el-icon></button>
              <span>{{ zoom }}%</span>
              <button type="button" aria-label="放大" @click="adjustZoom(10)"><el-icon><ZoomIn /></el-icon></button>
              <button type="button" aria-label="打印"><el-icon><Printer /></el-icon></button>
              <button type="button" aria-label="更多"><el-icon><MoreFilled /></el-icon></button>
            </div>
          </div>

          <article class="document-paper" :style="{ '--document-scale': `${zoom / 100}` }">
            <div class="paper-heading">
              <span>MASTER SERVICE AGREEMENT</span>
              <small>服务级别协议</small>
            </div>
            <section>
              <h2>1. DEFINITIONS.</h2>
              <p>"Services" means the consulting and technical implementation services provided by Provider to Client as described in the applicable Statement of Work. "Deliverables" means all work product, reports, software, and other materials developed specifically for Client.</p>
            </section>
            <section>
              <h2>2. SCOPE OF SERVICES.</h2>
              <p>Provider shall provide the Services and Deliverables set forth in each SOW. Each SOW shall be deemed a part of this Agreement. In the event of a conflict between this Agreement and an SOW, this Agreement shall prevail unless the SOW specifically states otherwise.</p>
            </section>
            <section>
              <h2>3. LIMITATION OF LIABILITY.</h2>
              <p>Notwithstanding any provision to the contrary, Provider's total aggregate liability arising out of or related to this Agreement shall be limited to $5,000,000 USD. Client waives all claims for incidental, consequential, or punitive damages under any legal theory whatsoever.</p>
            </section>
            <section>
              <h2>4. INTELLECTUAL PROPERTY.</h2>
              <p>Client shall own all right, title and interest in and to the Deliverables upon full payment of the applicable fees. Provider retains all rights to its pre-existing materials, tools, and methodologies used in the performance of the Services.</p>
            </section>
            <section>
              <h2>5. INDEMNIFICATION.</h2>
              <p>Provider shall indemnify, defend, and hold harmless Client from claims arising from a breach of this Agreement.</p>
            </section>
          </article>
        </main>

        <aside class="findings-panel">
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
                <RiskCard
                  v-for="risk in review.risks"
                  :key="risk.id"
                  :risk="risk"
                  :action="risk.action ?? 'pending'"
                  @select="selectRisk"
                />
              </div>
              <div v-if="loadError" class="findings-empty findings-empty--error" role="alert">{{ loadError }}</div>
              <div v-else-if="loading && !review.risks.length" class="findings-empty">正在加载审查结果…</div>
              <div v-else-if="!review.risks.length" class="findings-empty">暂无审查发现</div>
            </div>
            <div v-if="selectedRisk" class="selected-risk-note">
              已选中「{{ selectedRisk.section }}」{{ selectedRisk.title }}
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
            <ReviewAssistant :risk="selectedRisk" @locate="locateCitation" />
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

.console-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 360px;
  min-height: 680px;
  border: 1px solid var(--outline-soft);
  background: var(--surface);
}

.reader-panel {
  min-width: 0;
  overflow: auto;
  background: #eef2f8;
}

.reader-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  min-height: 62px;
  padding: 12px 24px;
  border-bottom: 1px solid var(--outline-soft);
  background: var(--surface);
}

.reader-toolbar__title {
  display: flex;
  align-items: center;
}

.reader-tools {
  display: flex;
  align-items: center;
  gap: 10px;
}

.reader-tools > span {
  color: var(--ink-muted);
  font-size: 11px;
}

.reader-tools button {
  display: grid;
  width: var(--control-height);
  height: var(--control-height);
  place-items: center;
  padding: 0;
  border: 0;
  border-radius: var(--radius-sm);
  color: var(--ink-muted);
  background: transparent;
  cursor: pointer;
}

.reader-tools button:hover {
  color: var(--action);
  background: var(--surface-low);
}

.document-paper {
  width: min(calc(100% - 48px), 720px);
  min-height: 980px;
  margin: 24px auto;
  padding: 44px 54px;
  border: 1px solid #c4ccd8;
  background: var(--surface);
  box-shadow: var(--shadow-sm);
  font-size: calc(14px * var(--document-scale));
}

.paper-heading {
  padding-bottom: 20px;
  border-bottom: 1px solid var(--outline-soft);
  text-align: center;
}

.paper-heading span,
.paper-heading small {
  display: block;
}

.paper-heading span {
  color: var(--ink);
  font-size: 21px;
  font-weight: 800;
  letter-spacing: 0.12em;
}

.paper-heading small {
  margin-top: 7px;
  color: var(--ink-muted);
}

.document-paper section {
  margin-top: 24px;
}

.document-paper h2 {
  display: inline;
  margin: 0;
  font-size: 15px;
}

.document-paper p {
  display: inline;
  margin: 0;
  color: #263448;
  line-height: 1.85;
}

.findings-panel {
  display: flex;
  min-width: 0;
  flex-direction: column;
  border-left: 1px solid var(--outline-soft);
  background: var(--surface);
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
  gap: 10px;
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

.selected-risk-note {
  margin: 0 20px 14px;
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  color: var(--ink-muted);
  background: var(--surface-low);
  font-size: 11px;
  line-height: 1.55;
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

@media (max-width: 1200px) {
  .console-layout {
    grid-template-columns: minmax(0, 1fr) 320px;
  }

  .document-paper {
    padding: 38px 40px;
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

  .console-layout {
    grid-template-columns: 1fr;
  }

  .findings-panel {
    border-top: 1px solid var(--outline-soft);
    border-left: 0;
  }

  .reader-toolbar {
    align-items: flex-start;
    flex-direction: column;
  }

  .document-paper {
    width: calc(100% - 24px);
    min-height: 680px;
    margin: 12px auto;
    padding: 28px 22px;
  }

  .paper-heading span {
    font-size: 16px;
  }
}
</style>
