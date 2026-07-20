<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowRight, Check, Setting, TrendCharts } from '@element-plus/icons-vue'
import ClauseCard from '@/components/review/ClauseCard.vue'
import ReviewFooter from '@/components/review/ReviewFooter.vue'
import ReviewStepper from '@/components/review/ReviewStepper.vue'
import { useReviewStore } from '@/stores/review'
import type { ReviewClause } from '@/types'

const review = useReviewStore()
const router = useRouter()
const route = useRoute()
const model = ref('Legal-LLM v2（正式版）')
const logic = ref('标准审查标记')

const financeClauses = computed(() => review.clauses.filter((clause) => clause.group === 'finance'))
const complianceClauses = computed(() => review.clauses.filter((clause) => clause.group === 'compliance'))
const enabledCount = computed(() => review.clauses.filter((clause) => clause.enabled).length)
const disabledCount = computed(() => review.clauses.filter((clause) => !clause.enabled && !clause.disabled).length)

onMounted(() => review.goToStep(Number(route.meta.reviewStep) || 3))

function isGroupEnabled(clauses: ReviewClause[]) {
  return clauses.filter((clause) => !clause.disabled).every((clause) => clause.enabled)
}

function toggleAll(clauses: ReviewClause[]) {
  const target = !isGroupEnabled(clauses)
  clauses.forEach((clause) => {
    if (clause.disabled || clause.enabled === target) return
    review.toggleClause(clause.id)
  })
}

function updateSensitivity(event: Event) {
  review.setSensitivity(Number((event.target as HTMLInputElement).value))
}

async function startAnalysis() {
  review.startAnalysis()
  await router.push({ name: 'review-console' })
}

async function goPrevious() {
  review.previousStep()
  await router.push({ name: 'review-templates' })
}
</script>

<template>
  <div class="review-page rules-page">
    <ReviewStepper :current="review.currentStep" />

    <header class="page-heading">
      <h1>审查规则与约束配置</h1>
      <p>配置您的 AI 分析参数。选择要在文档批次中识别并标记的特定法律条款和运营约束。</p>
    </header>

    <div class="rules-layout">
      <main class="rules-main">
        <section class="rule-group" aria-labelledby="finance-title">
          <div class="group-heading">
            <h2 id="finance-title">财务与支付</h2>
            <button type="button" @click="toggleAll(financeClauses)">
              {{ isGroupEnabled(financeClauses) ? '取消全选' : '全选' }}
            </button>
          </div>
          <div class="clause-grid">
            <ClauseCard v-for="clause in financeClauses" :key="clause.id" :clause="clause" @toggle="review.toggleClause" />
          </div>
        </section>

        <section class="rule-group" aria-labelledby="compliance-title">
          <div class="group-heading">
            <h2 id="compliance-title">合规与运营</h2>
            <button type="button" @click="toggleAll(complianceClauses)">
              {{ isGroupEnabled(complianceClauses) ? '取消全选' : '全选' }}
            </button>
          </div>
          <div class="clause-grid clause-grid--compliance">
            <ClauseCard v-for="clause in complianceClauses" :key="clause.id" :clause="clause" @toggle="review.toggleClause" />
            <button class="custom-rule" type="button">
              <el-icon aria-hidden="true"><Setting /></el-icon>
              <strong>添加自定义规则</strong>
              <span>扩展您的审查范围</span>
            </button>
          </div>
        </section>

        <section class="tuning-panel" aria-labelledby="tuning-title">
          <div class="tuning-heading">
            <span class="tuning-icon" aria-hidden="true"><el-icon><TrendCharts /></el-icon></span>
            <div>
              <h2 id="tuning-title">模型微调</h2>
              <p>调整检测灵敏度与标记方式。</p>
            </div>
          </div>
          <div class="tuning-grid">
            <label class="sensitivity-control">
              <span class="field-label"><b>检测灵敏度</b><strong>{{ review.sensitivity }}%</strong></span>
              <input
                data-test="sensitivity"
                type="range"
                min="0"
                max="100"
                :value="review.sensitivity"
                @input="updateSensitivity"
              />
              <span class="range-labels"><small>宽泛</small><small>精准</small></span>
            </label>
            <label class="select-control">
              <span class="field-label"><b>分析模型</b></span>
              <select v-model="model">
                <option>Legal-LLM v2（正式版）</option>
                <option>Legal-LLM v2（快速版）</option>
              </select>
            </label>
            <label class="select-control">
              <span class="field-label"><b>标记逻辑</b></span>
              <select v-model="logic">
                <option>标准审查标记</option>
                <option>仅标记高风险</option>
              </select>
            </label>
          </div>
        </section>
      </main>

      <aside class="config-preview">
        <h2>配置预览</h2>
        <dl>
          <div><dt>已选条款</dt><dd>{{ enabledCount }}</dd></div>
          <div><dt>潜在违规</dt><dd class="warning-value">{{ disabledCount + 3 }} 项激活</dd></div>
          <div><dt>预计处理时长</dt><dd>~1.2 分钟</dd></div>
          <div><dt>批次大小</dt><dd>{{ review.files.length }} 份文件</dd></div>
        </dl>
        <div class="ready-note">
          <div><span class="ready-dot"></span><strong>模型就绪状态：最佳</strong></div>
          <p>继续操作将启动高精度扫描。结果将根据 <b>{{ model.split('（')[0] }}</b> 进行对比。</p>
        </div>
        <el-button data-test="start-analysis" type="primary" size="large" @click="startAnalysis">
          开始全量分析
          <el-icon aria-hidden="true"><ArrowRight /></el-icon>
        </el-button>
        <el-button plain size="large">保存配置为模板</el-button>
      </aside>
    </div>

    <ReviewFooter previous-label="上一步：选择范本" next-label="开始分析" @previous="goPrevious" @next="startAnalysis">
      {{ enabledCount }} 项规则已启用
    </ReviewFooter>
  </div>
</template>

<style scoped>
.review-page {
  width: min(1440px, 100%);
  margin: 0 auto;
}

.page-heading {
  margin-bottom: 28px;
}

.page-heading h1 {
  margin-bottom: 8px;
  font-size: 36px;
}

.page-heading p {
  max-width: 820px;
  margin: 0;
  color: var(--ink-muted);
  font-size: 15px;
}

.rules-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 300px;
  align-items: start;
  gap: 28px;
}

.rules-main,
.config-preview {
  min-width: 0;
}

.rules-main {
  display: grid;
  gap: 28px;
}

.rule-group {
  display: grid;
  gap: 14px;
}

.group-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.group-heading h2 {
  margin: 0;
  font-size: 16px;
}

.group-heading button {
  min-height: var(--control-height);
  padding: 0 8px;
  border: 0;
  color: var(--action);
  background: transparent;
  font-weight: 700;
  cursor: pointer;
}

.clause-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.clause-grid--compliance {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.custom-rule {
  display: flex;
  min-height: 190px;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 18px;
  border: 1px dashed var(--outline);
  border-radius: var(--radius-lg);
  color: var(--ink-muted);
  background: transparent;
  cursor: pointer;
}

.custom-rule:hover {
  border-color: var(--action);
  color: var(--action);
  background: var(--surface-low);
}

.custom-rule .el-icon {
  font-size: 28px;
}

.custom-rule span {
  font-size: 12px;
}

.tuning-panel {
  padding: 20px;
  border: 1px solid #a8c5ff;
  border-radius: var(--radius-md);
  background: var(--action-soft);
}

.tuning-heading {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 24px;
}

.tuning-icon {
  display: grid;
  width: 42px;
  height: 42px;
  place-items: center;
  border-radius: var(--radius-sm);
  color: #ffffff;
  background: var(--action);
  font-size: 22px;
}

.tuning-heading h2,
.tuning-heading p {
  margin: 0;
}

.tuning-heading h2 {
  font-size: 18px;
}

.tuning-heading p {
  margin-top: 3px;
  color: var(--ink-muted);
  font-size: 12px;
}

.tuning-grid {
  display: grid;
  grid-template-columns: minmax(180px, 1.1fr) repeat(2, minmax(170px, 1fr));
  align-items: end;
  gap: 22px;
}

.sensitivity-control,
.select-control {
  display: grid;
  gap: 9px;
}

.field-label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.field-label strong {
  color: var(--action);
  font-size: 20px;
}

.sensitivity-control input[type="range"] {
  width: 100%;
  accent-color: var(--action);
}

.range-labels {
  display: flex;
  justify-content: space-between;
  color: #7a89a0;
  font-size: 11px;
}

.select-control select {
  width: 100%;
  min-height: var(--control-height);
  padding: 8px 10px;
  border: 1px solid var(--outline);
  border-radius: var(--radius-sm);
  color: var(--ink);
  background: var(--surface);
}

.config-preview {
  display: grid;
  gap: 18px;
  padding: 24px;
  border: 1px solid var(--outline);
  border-radius: var(--radius-md);
  background: var(--surface);
  box-shadow: var(--shadow-sm);
}

.config-preview h2 {
  margin: 0;
  font-size: 22px;
}

.config-preview dl {
  display: grid;
  gap: 0;
  margin: 0;
}

.config-preview dl > div {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 16px 0;
  border-bottom: 1px solid var(--outline-soft);
}

.config-preview dt {
  color: var(--ink-muted);
}

.config-preview dd {
  margin: 0;
  font-size: 17px;
  font-weight: 700;
}

.config-preview dd:not(.warning-value) {
  color: var(--action);
}

.config-preview .warning-value {
  color: var(--danger);
}

.ready-note {
  padding: 16px;
  border: 1px solid var(--outline-soft);
  border-radius: var(--radius-md);
  background: var(--surface-low);
}

.ready-note > div {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}

.ready-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #16b364;
}

.ready-note p {
  margin: 12px 0 0;
  color: var(--ink-muted);
  font-size: 12px;
  line-height: 1.7;
}

.config-preview .el-button {
  width: 100%;
}

.config-preview .el-button .el-icon {
  margin-left: 8px;
}

@media (max-width: 1100px) {
  .rules-layout {
    grid-template-columns: 1fr;
  }

  .config-preview {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    align-items: start;
  }

  .config-preview h2,
  .config-preview dl,
  .config-preview .ready-note {
    grid-column: 1 / -1;
  }

  .config-preview .el-button {
    width: auto;
  }
}

@media (max-width: 760px) {
  .page-heading h1 {
    font-size: 28px;
  }

  .clause-grid,
  .clause-grid--compliance,
  .tuning-grid,
  .config-preview {
    grid-template-columns: 1fr;
  }

  .config-preview h2,
  .config-preview dl,
  .config-preview .ready-note {
    grid-column: auto;
  }

  .config-preview .el-button {
    width: 100%;
  }
}
</style>
