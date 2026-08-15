<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowRight, Setting } from '@element-plus/icons-vue'
import ClauseCard from '@/components/review/ClauseCard.vue'
import ReviewFooter from '@/components/review/ReviewFooter.vue'
import ReviewStepper from '@/components/review/ReviewStepper.vue'
import { useReviewStore } from '@/stores/review'
import type { ReviewClause } from '@/types'

const review = useReviewStore()
const router = useRouter()
const route = useRoute()

const financeClauses = computed(() => review.clauses.filter((clause) => clause.group === 'finance'))
const complianceClauses = computed(() => review.clauses.filter((clause) => clause.group === 'compliance'))
const enabledCount = computed(() => review.clauses.filter((clause) => clause.enabled).length)

const showCreateRule = ref(false)
const creatingRule = ref(false)
const ruleError = ref('')
const newRuleName = ref('')
const newRuleCategory = ref('compliance')
const newRuleSeverity = ref<'low' | 'medium' | 'high'>('medium')
const newRuleDescription = ref('')

onMounted(() => {
  review.goToStep(Number(route.meta.reviewStep) || 3)
  void review.initialize()
})

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

async function createRule() {
  creatingRule.value = true
  ruleError.value = ''
  try {
    await review.createRule({
      name: newRuleName.value.trim() || '自定义规则',
      category: newRuleCategory.value,
      severity: newRuleSeverity.value,
      definition: { description: newRuleDescription.value.trim() || '自定义审查规则。' },
    })
    showCreateRule.value = false
    newRuleName.value = ''
    newRuleDescription.value = ''
  } catch (err) {
    ruleError.value = err instanceof Error ? err.message : '创建规则失败'
  } finally {
    creatingRule.value = false
  }
}

async function saveConfiguration() {
  try {
    await review.createTemplate({
      name: '自定义配置范本',
      category: '交易类',
      description: '由当前规则配置生成的审查范本。',
    })
  } catch {
    // 错误已在 store 中记录
  }
}

async function startAnalysis() {
  try {
    await review.startAnalysis()
    await router.push({ name: 'review-console' })
  } catch {
    // 错误已在 store 中记录并展示，阻止跳转
  }
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
        <section class="detection-panel" aria-labelledby="detection-title">
          <div class="detection-copy">
            <h2 id="detection-title">检测设置</h2>
            <p>调整检测灵敏度，控制审查标记的严格程度。</p>
          </div>
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
        </section>

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
            <button class="custom-rule" type="button" @click="showCreateRule = true">
              <el-icon aria-hidden="true"><Setting /></el-icon>
              <strong>添加自定义规则</strong>
              <span>扩展您的审查范围</span>
            </button>
          </div>
        </section>

      </main>

      <aside class="config-preview">
        <h2>配置预览</h2>
        <dl>
          <div><dt>已启用条款</dt><dd>{{ enabledCount }} 项</dd></div>
          <div><dt>检测灵敏度</dt><dd>{{ review.sensitivity }}%</dd></div>
          <div><dt>就绪文件</dt><dd>{{ review.readyCount }} 份</dd></div>
          <div><dt>批次大小</dt><dd>{{ review.files.length }} 份文件</dd></div>
        </dl>
        <el-button data-test="start-analysis" type="primary" size="large" @click="startAnalysis">
          开始全量分析
          <el-icon aria-hidden="true"><ArrowRight /></el-icon>
        </el-button>
        <el-button plain size="large" @click="saveConfiguration">保存配置为模板</el-button>
      </aside>
    </div>

    <ReviewFooter previous-label="上一步：选择范本" next-label="开始分析" @previous="goPrevious" @next="startAnalysis">
      {{ enabledCount }} 项规则已启用
    </ReviewFooter>

    <el-dialog v-model="showCreateRule" title="添加自定义规则" width="min(520px, 92vw)">
      <form class="create-form" @submit.prevent="createRule">
        <label>
          <span>规则名称</span>
          <input v-model="newRuleName" type="text" placeholder="例如：检查履约保函条款" />
        </label>
        <label>
          <span>分类</span>
          <select v-model="newRuleCategory">
            <option value="compliance">合规与运营</option>
            <option value="finance">财务与支付</option>
          </select>
        </label>
        <label>
          <span>风险等级</span>
          <select v-model="newRuleSeverity">
            <option value="low">低</option>
            <option value="medium">中</option>
            <option value="high">高</option>
          </select>
        </label>
        <label>
          <span>规则描述</span>
          <textarea v-model="newRuleDescription" rows="3" placeholder="描述该规则要识别的问题"></textarea>
        </label>
        <p v-if="ruleError" class="create-error">{{ ruleError }}</p>
        <div class="create-form__actions">
          <el-button @click="showCreateRule = false">取消</el-button>
          <el-button type="primary" native-type="submit" :loading="creatingRule">创建规则</el-button>
        </div>
      </form>
    </el-dialog>
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

.detection-panel {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  padding: 16px 20px;
  border: 1px solid var(--outline);
  border-radius: var(--radius-md);
  background: var(--surface);
}

.detection-copy h2,
.detection-copy p {
  margin: 0;
}

.detection-copy h2 {
  font-size: 16px;
}

.detection-copy p {
  margin-top: 3px;
  color: var(--ink-muted);
  font-size: 12px;
}

.detection-panel .sensitivity-control {
  flex: 0 1 340px;
}

.sensitivity-control {
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

.config-preview dd {
  color: var(--action);
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
  .config-preview dl {
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
  .config-preview {
    grid-template-columns: 1fr;
  }

  .detection-panel {
    flex-direction: column;
    align-items: stretch;
  }

  .config-preview h2,
  .config-preview dl {
    grid-column: auto;
  }

  .config-preview .el-button {
    width: 100%;
  }
}

.create-form {
  display: grid;
  gap: 16px;
}

.create-form label:not(.create-form__check) {
  display: grid;
  gap: 7px;
}

.create-form label > span {
  font-size: 12px;
  font-weight: 700;
}

.create-form input[type="text"],
.create-form textarea,
.create-form select {
  width: 100%;
  padding: 8px 10px;
  border: 1px solid var(--outline);
  border-radius: var(--radius-sm);
  color: var(--ink);
  background: var(--surface);
}

.create-error {
  margin: 0;
  color: var(--danger);
  font-size: 12px;
}

.create-form__actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>
