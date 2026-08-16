<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { ArrowRight, Setting, Upload } from '@element-plus/icons-vue'
import { useRouter } from 'vue-router'
import { useReviewStore } from '@/stores/review'
import ClauseCard from '@/components/review/ClauseCard.vue'
import type { ReviewClause } from '@/types'

const emit = defineEmits<{
  started: []
}>()

// 单文档审查模式：仅分析指定文档（从文件队列进入）
const props = defineProps<{
  documentId?: string
}>()

const review = useReviewStore()
const router = useRouter()

const financeClauses = computed(() => review.clauses.filter((clause) => clause.group === 'finance'))
const complianceClauses = computed(() => review.clauses.filter((clause) => clause.group === 'compliance'))
const enabledCount = computed(() => review.clauses.filter((clause) => clause.enabled).length)

const showCreateRule = ref(false)
const creatingRule = ref(false)
const savingConfig = ref(false)
const starting = ref(false)
const ruleError = ref('')
const newRuleName = ref('')
const newRuleCategory = ref('compliance')
const newRuleSeverity = ref<'low' | 'medium' | 'high'>('medium')
const newRuleDescription = ref('')
const editingClause = ref<ReviewClause | null>(null)

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

function openCreateRule() {
  editingClause.value = null
  newRuleName.value = ''
  newRuleCategory.value = 'compliance'
  newRuleSeverity.value = 'medium'
  newRuleDescription.value = ''
  ruleError.value = ''
  showCreateRule.value = true
}

function openEditRule(clause: ReviewClause) {
  editingClause.value = clause
  newRuleName.value = clause.title
  newRuleCategory.value = clause.category ?? clause.group
  newRuleSeverity.value = clause.severity ?? 'medium'
  newRuleDescription.value = clause.description
  ruleError.value = ''
  showCreateRule.value = true
}

async function saveRule() {
  creatingRule.value = true
  ruleError.value = ''
  try {
    const payload = {
      name: newRuleName.value.trim() || (editingClause.value ? editingClause.value.title : '自定义规则'),
      category: newRuleCategory.value,
      severity: newRuleSeverity.value,
      definition: { description: newRuleDescription.value.trim() || '自定义审查规则。' },
    }
    if (editingClause.value) {
      await review.updateRule(editingClause.value.id, payload)
      ElMessage.success('规则已更新（生成新版本 v' + ((editingClause.value.version ?? 1) + 1) + '）')
    } else {
      await review.createRule(payload)
      ElMessage.success('规则已创建')
    }
    showCreateRule.value = false
    editingClause.value = null
    newRuleName.value = ''
    newRuleDescription.value = ''
  } catch (err) {
    ruleError.value = err instanceof Error ? err.message : '保存规则失败'
  } finally {
    creatingRule.value = false
  }
}

async function saveConfiguration() {
  savingConfig.value = true
  ruleError.value = ''
  try {
    await review.saveConfiguration()
    ElMessage.success('已将当前规则选择、灵敏度与偏好保存为审查配置')
  } catch (err) {
    ruleError.value = err instanceof Error ? err.message : '保存配置失败'
  } finally {
    savingConfig.value = false
  }
}

async function startAnalysis() {
  starting.value = true
  ruleError.value = ''
  try {
    await review.startAnalysis(props.documentId || undefined)
    ElMessage.success('分析已启动')
    emit('started')
  } catch (err) {
    const message = err instanceof Error ? err.message : '分析启动失败，请稍后重试'
    ElMessage.error(message)
    ruleError.value = message
  } finally {
    starting.value = false
  }
}

function goToUpload() {
  void router.push({ name: 'review-upload' })
}
</script>
<template>
  <div class="config-panel">
    <div class="config-summary">
      <div><span>就绪文件</span><strong>{{ review.readyCount }} 份</strong></div>
      <div><span>批次大小</span><strong>{{ review.files.length }} 份</strong></div>
      <div><span>已启用规则</span><strong>{{ enabledCount }} 项</strong></div>
    </div>

    <div v-if="!review.files.length" class="config-upload-hint">
      <p>尚未添加待审文档，请先上传并解析文档。</p>
      <el-button type="primary" plain @click="goToUpload">
        <el-icon aria-hidden="true"><Upload /></el-icon>
        前往文档上传
      </el-button>
    </div>

    <!-- 配置与分析操作置顶：范本选择/条款设置详情在下 -->
    <div class="config-preferences">
      <label class="preference-row">
        <span>检测灵敏度</span>
        <input
          type="range"
          min="0"
          max="100"
          :value="review.sensitivity"
          aria-label="检测灵敏度"
          @input="updateSensitivity"
        />
        <strong>{{ review.sensitivity }}%</strong>
      </label>
      <label class="preference-row">
        <span>分析方案</span>
        <select v-model="review.analysisProfile" aria-label="分析方案">
          <option value="accurate">精准（推荐）</option>
          <option value="fast">快速</option>
        </select>
      </label>
      <label class="preference-row">
        <span>标记模式</span>
        <select v-model="review.markingMode" aria-label="标记模式">
          <option value="standard">标准标记</option>
          <option value="high_only">仅标记高风险</option>
        </select>
      </label>
    </div>

    <p v-if="ruleError" class="config-error" role="alert">{{ ruleError }}</p>
    <p v-if="review.configurationId && !review.configurationDirty" class="config-hint">
      本次分析将优先使用已保存配置（修订 {{ review.configurationRevision }}）
    </p>

    <div class="config-actions">
      <el-button
        data-test="start-analysis"
        type="primary"
        size="large"
        :loading="starting || ['loading', 'queued', 'parsing', 'running'].includes(review.analysisStatus)"
        @click="startAnalysis"
      >
        开始全量分析
        <el-icon aria-hidden="true"><ArrowRight /></el-icon>
      </el-button>
      <el-button plain size="large" :loading="savingConfig" @click="saveConfiguration">保存当前配置</el-button>
    </div>

    <section class="config-section" aria-labelledby="config-template-title">
      <div class="config-section__heading">
        <h3 id="config-template-title">范本选择</h3>
        <span>{{ review.templates.length }} 个可用范本</span>
      </div>
      <div v-if="review.templates.length" class="template-list">
        <label
          v-for="template in review.templates"
          :key="template.id"
          class="template-option"
          :class="{ 'template-option--selected': review.selectedTemplateId === template.id }"
        >
          <input
            type="radio"
            name="review-template"
            :value="template.id"
            :checked="review.selectedTemplateId === template.id"
            @change="review.selectTemplate(template.id)"
          />
          <span class="template-option__copy">
            <strong>{{ template.name }}</strong>
            <span>{{ template.description }}</span>
          </span>
          <span class="template-option__meta">{{ template.checks }} 条规则</span>
        </label>
      </div>
      <p v-else class="config-empty">暂无可用范本</p>
    </section>

    <section class="config-section" aria-labelledby="config-clauses-title">
      <div class="config-section__heading">
        <h3 id="config-clauses-title">条款设置</h3>
        <button type="button" class="config-add-rule" @click="openCreateRule">
          <el-icon aria-hidden="true"><Setting /></el-icon>
          添加自定义规则
        </button>
      </div>

      <div class="clause-group">
        <div class="clause-group__head">
          <h4>财务与支付</h4>
          <button type="button" @click="toggleAll(financeClauses)">
            {{ isGroupEnabled(financeClauses) ? '取消全选' : '全选' }}
          </button>
        </div>
        <div class="clause-grid">
          <ClauseCard
            v-for="clause in financeClauses"
            :key="clause.id"
            :clause="clause"
            @toggle="review.toggleClause"
            @edit="openEditRule"
          />
        </div>
      </div>

      <div class="clause-group">
        <div class="clause-group__head">
          <h4>合规与运营</h4>
          <button type="button" @click="toggleAll(complianceClauses)">
            {{ isGroupEnabled(complianceClauses) ? '取消全选' : '全选' }}
          </button>
        </div>
        <div class="clause-grid">
          <ClauseCard
            v-for="clause in complianceClauses"
            :key="clause.id"
            :clause="clause"
            @toggle="review.toggleClause"
            @edit="openEditRule"
          />
        </div>
      </div>
    </section>

    <el-dialog v-model="showCreateRule" :title="editingClause ? `编辑规则：${editingClause.title}` : '添加自定义规则'" width="min(520px, 92vw)">
      <form class="rule-form" @submit.prevent="saveRule">
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
        <p v-if="ruleError" class="config-error">{{ ruleError }}</p>
        <div class="rule-form__actions">
          <el-button @click="showCreateRule = false">取消</el-button>
          <el-button type="primary" native-type="submit" :loading="creatingRule">{{ editingClause ? '保存修改' : '创建规则' }}</el-button>
        </div>
      </form>
    </el-dialog>
  </div>
</template>
<style scoped>
.config-panel {
  display: flex;
  min-height: 0;
  flex: 1;
  flex-direction: column;
  gap: 14px;
  overflow-y: auto;
  padding: 16px 20px 20px;
}

.config-summary {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.config-summary > div {
  display: grid;
  gap: 4px;
  padding: 12px;
  border: 1px solid var(--outline-soft);
  border-radius: var(--radius-md);
  background: var(--surface-low);
}

.config-summary span {
  color: var(--ink-muted);
  font-size: 11px;
}

.config-summary strong {
  font-size: 18px;
}

.config-upload-hint {
  display: grid;
  justify-items: start;
  gap: 8px;
  padding: 12px;
  border: 1px dashed var(--outline-soft);
  border-radius: var(--radius-md);
}

.config-upload-hint p {
  margin: 0;
  color: var(--ink-muted);
  font-size: 12px;
}

.config-section {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.config-section__heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.config-section__heading h3 {
  margin: 0;
  font-size: 14px;
}

.config-section__heading span {
  color: var(--ink-muted);
  font-size: 11px;
}

.config-add-rule {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 10px;
  border: 1px solid var(--outline-soft);
  border-radius: var(--radius-sm);
  color: var(--action);
  background: var(--surface);
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
}

.template-list {
  display: grid;
  gap: 8px;
}

.template-option {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid var(--outline-soft);
  border-radius: var(--radius-md);
  cursor: pointer;
}

.template-option--selected {
  border-color: var(--action);
  background: var(--action-soft);
}

.template-option__copy {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
  gap: 2px;
}

.template-option__copy strong {
  font-size: 13px;
}

.template-option__copy span {
  overflow: hidden;
  color: var(--ink-muted);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.template-option__meta {
  color: var(--ink-muted);
  font-size: 10px;
  white-space: nowrap;
}

.config-empty {
  margin: 0;
  padding: 12px;
  border: 1px dashed var(--outline-soft);
  border-radius: var(--radius-md);
  color: var(--ink-muted);
  font-size: 12px;
  text-align: center;
}

.clause-group {
  display: grid;
  gap: 8px;
}

.clause-group__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.clause-group__head h4 {
  margin: 0;
  font-size: 12px;
  color: var(--ink-muted);
}

.clause-group__head button {
  padding: 0;
  border: 0;
  color: var(--action);
  background: transparent;
  font-size: 11px;
  cursor: pointer;
}

.clause-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.config-preferences {
  display: grid;
  gap: 10px;
  padding: 12px;
  border: 1px solid var(--outline-soft);
  border-radius: var(--radius-md);
  background: var(--surface-low);
}

.preference-row {
  display: grid;
  grid-template-columns: 90px 1fr 56px;
  align-items: center;
  gap: 10px;
  font-size: 12px;
}

.preference-row input[type='range'] {
  width: 100%;
}

.preference-row select {
  grid-column: 2 / -1;
  min-height: 32px;
  border: 1px solid var(--outline-soft);
  border-radius: var(--radius-sm);
  background: var(--surface);
}

.config-error {
  margin: 0;
  color: var(--danger);
  font-size: 12px;
}

.config-hint {
  margin: 0;
  color: var(--ink-muted);
  font-size: 11px;
}

.config-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.rule-form {
  display: grid;
  gap: 12px;
}

.rule-form label {
  display: grid;
  gap: 4px;
  font-size: 12px;
}

.rule-form input,
.rule-form select,
.rule-form textarea {
  min-height: 32px;
  padding: 4px 8px;
  border: 1px solid var(--outline-soft);
  border-radius: var(--radius-sm);
  background: var(--surface);
}

.rule-form__actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}
</style>
