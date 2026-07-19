<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Download,
  MoreFilled,
  Printer,
  ZoomIn,
  ZoomOut,
} from '@element-plus/icons-vue'
import RiskCard, { type RiskAction } from '@/components/review/RiskCard.vue'
import ReviewFooter from '@/components/review/ReviewFooter.vue'
import ReviewStepper from '@/components/review/ReviewStepper.vue'
import { useReviewStore } from '@/stores/review'

const review = useReviewStore()
const router = useRouter()
const route = useRoute()
const selectedRiskId = ref('unlimited-liability')
const riskActions = ref<Record<string, RiskAction>>({})
const zoom = ref(100)
let analysisTimer: ReturnType<typeof setTimeout> | null = null

function scheduleAnalysisCompletion() {
  if (analysisTimer || review.analysisStatus !== 'running') return
  analysisTimer = setTimeout(() => {
    review.completeAnalysis()
    analysisTimer = null
  }, 450)
}

onMounted(() => {
  review.goToStep(Number(route.meta.reviewStep) || 4)
  if (review.analysisStatus === 'idle') review.startAnalysis()
  scheduleAnalysisCompletion()
})

onBeforeUnmount(() => {
  if (analysisTimer) clearTimeout(analysisTimer)
})

function selectRisk(id: string) {
  selectedRiskId.value = id
}

function approveDraft() {
  review.approveDraft()
}

function rejectChanges() {
  review.rejectChanges()
}

function exportReport() {
  // 演示页面只展示导出入口，不生成真实报告或调用后端。
}

function adjustZoom(amount: number) {
  zoom.value = Math.min(120, Math.max(80, zoom.value + amount))
}

async function goPrevious() {
  review.previousStep()
  await router.push({ name: 'review-rules' })
}
</script>

<template>
  <div class="console-page">
    <ReviewStepper :current="review.currentStep" />

    <div class="console-header">
      <div>
        <div class="console-title-row">
          <h1>AI 审查分析</h1>
          <span class="demo-badge">演示分析</span>
        </div>
        <p>服务级别协议_v4.pdf · 最后修改：2023 年 10 月 24 日 · 14 页</p>
      </div>
      <span class="engine-badge">BETA ENGINE 2.4</span>
    </div>

    <div class="console-layout">
      <main class="reader-panel">
        <div class="reader-toolbar">
          <div class="reader-toolbar__title"><strong>文档正文</strong><span>第 3 节 / 14</span></div>
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
          <section class="highlight-block highlight-block--danger">
            <h2>3. LIMITATION OF LIABILITY.</h2>
            <p>Notwithstanding any provision to the contrary, Provider's total aggregate liability arising out of or related to this Agreement shall be limited to $5,000,000 USD. Client waives all claims for incidental, consequential, or punitive damages under any legal theory whatsoever.</p>
          </section>
          <section>
            <h2>4. INTELLECTUAL PROPERTY.</h2>
            <p>Client shall own all right, title and interest in and to the Deliverables upon full payment of the applicable fees. Provider retains all rights to its pre-existing materials, tools, and methodologies used in the performance of the Services.</p>
          </section>
          <section class="highlight-block highlight-block--info">
            <h2>5. INDEMNIFICATION.</h2>
            <p>Provider shall indemnify, defend, and hold harmless Client from claims arising from a breach of this Agreement.</p>
          </section>
        </article>
      </main>

      <aside class="findings-panel">
        <div class="findings-heading">
          <div><h2>AI 审查分析</h2><span class="demo-badge">演示分析</span></div>
          <span class="engine-badge">BETA ENGINE 2.4</span>
        </div>
        <div class="metrics-grid">
          <div><span>发现问题</span><strong>12</strong></div>
          <div><span>风险评分</span><strong class="risk-score">中</strong></div>
        </div>
        <div class="findings-section">
          <div class="findings-section__title"><h3>核心风险</h3><span>点击查看条款</span></div>
          <div class="risk-list">
            <RiskCard
              v-for="risk in review.risks"
              :key="risk.id"
              :risk="risk"
              :action="riskActions[risk.id] ?? 'pending'"
              @select="selectRisk"
            />
          </div>
        </div>
        <div class="selected-risk-note" v-if="selectedRiskId">
          已定位到 {{ review.risks.find((risk) => risk.id === selectedRiskId)?.section }}，正文中的高亮段落与此发现对应。
        </div>
        <div class="console-actions">
          <el-button type="danger" plain :disabled="review.analysisStatus !== 'complete'" @click="rejectChanges">拒绝更改</el-button>
          <el-button
            data-test="approve-draft"
            type="primary"
            :disabled="review.analysisStatus !== 'complete'"
            @click="approveDraft"
          >批准草案</el-button>
          <el-button plain @click="exportReport">
            <el-icon aria-hidden="true"><Download /></el-icon>
            导出详细报告
          </el-button>
        </div>
      </aside>
    </div>

    <ReviewFooter previous-label="返回规则设置" next-label="分析完成" :next-disabled="true" @previous="goPrevious">
      <span v-if="review.analysisStatus === 'running'">演示分析正在运行，请稍候…</span>
      <span v-else>结果仅用于界面演示，不代表真实后端审查结论。</span>
    </ReviewFooter>
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

.console-title-row,
.findings-heading > div,
.reader-toolbar__title,
.reader-tools,
.findings-section__title {
  display: flex;
  align-items: center;
}

.console-title-row {
  gap: 12px;
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

.demo-badge,
.engine-badge {
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  padding: 3px 9px;
  border-radius: var(--radius-sm);
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.03em;
  white-space: nowrap;
}

.demo-badge {
  color: var(--action);
  background: var(--action-soft);
}

.engine-badge {
  color: var(--action);
  background: var(--action-soft);
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
  gap: 10px;
}

.reader-toolbar__title span,
.reader-tools > span {
  color: var(--ink-muted);
  font-size: 11px;
}

.reader-tools {
  gap: 10px;
}

.reader-tools button {
  display: grid;
  width: 32px;
  height: 32px;
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

.highlight-block {
  padding: 16px 18px;
}

.highlight-block--danger {
  border-left: 4px solid var(--danger);
  background: #fff3f1;
}

.highlight-block--info {
  border-left: 4px solid var(--action);
  background: #eef4ff;
}

.findings-panel {
  display: flex;
  min-width: 0;
  flex-direction: column;
  border-left: 1px solid var(--outline-soft);
  background: var(--surface);
}

.findings-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 24px 20px 18px;
  border-bottom: 1px solid var(--outline-soft);
}

.findings-heading > div {
  flex-wrap: wrap;
  gap: 8px;
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

.selected-risk-note {
  margin: 0 20px 14px;
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  color: var(--ink-muted);
  background: var(--surface-low);
  font-size: 11px;
  line-height: 1.55;
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
  .console-title-row h1 {
    font-size: 28px;
  }

  .console-header {
    align-items: stretch;
    flex-direction: column;
  }

  .console-header .engine-badge {
    align-self: flex-start;
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
