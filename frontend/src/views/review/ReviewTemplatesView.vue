<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, ArrowRight, InfoFilled, Search } from '@element-plus/icons-vue'
import ReviewFooter from '@/components/review/ReviewFooter.vue'
import ReviewStepper from '@/components/review/ReviewStepper.vue'
import TemplateCard from '@/components/review/TemplateCard.vue'
import { useReviewStore } from '@/stores/review'

const review = useReviewStore()
const router = useRouter()
const route = useRoute()
const query = ref('')
const activeCategory = ref('所有范本')
const categories = ['所有范本', '交易类', '雇佣类', '知识产权']

const categoryMap: Record<string, string[]> = {
  交易类: ['商业合同', '保密协议', '房地产'],
  雇佣类: ['人事政策'],
  知识产权: ['知识产权法'],
}

const filteredTemplates = computed(() => {
  const normalizedQuery = query.value.trim().toLowerCase()
  return review.templates.filter((template) => {
    const matchesCategory =
      activeCategory.value === '所有范本' || categoryMap[activeCategory.value]?.includes(template.category)
    const matchesQuery =
      !normalizedQuery || `${template.name} ${template.category} ${template.description}`.toLowerCase().includes(normalizedQuery)
    return matchesCategory && matchesQuery
  })
})

const selectedTemplate = computed(
  () => review.templates.find((template) => template.id === review.selectedTemplateId) ?? review.templates[0],
)

onMounted(() => {
  review.goToStep(Number(route.meta.reviewStep) || 2)
  void review.initialize()
})

function selectTemplate(id: string) {
  review.selectTemplate(id)
}

async function goNext() {
  review.nextStep()
  await router.push({ name: 'review-rules' })
}

async function goPrevious() {
  review.previousStep()
  await router.push({ name: 'review-upload' })
}
</script>

<template>
  <div class="review-page templates-page">
    <ReviewStepper :current="review.currentStep" />

    <header class="page-heading">
      <h1>选择分析范本</h1>
      <p>为您的文档选择合适的法律框架。AI 将根据所选范本应用特定的合规检查和风险评估。</p>
    </header>

    <div class="templates-layout">
      <main class="templates-main">
        <div class="template-controls">
          <div class="category-chips" aria-label="范本分类">
            <button
              v-for="category in categories"
              :key="category"
              class="category-chip"
              :class="{ 'category-chip--active': activeCategory === category }"
              type="button"
              @click="activeCategory = category"
            >
              {{ category }}
            </button>
          </div>
          <label class="template-search">
            <span class="sr-only">搜索范本</span>
            <el-icon aria-hidden="true"><Search /></el-icon>
            <input v-model="query" type="search" placeholder="搜索范本..." />
          </label>
        </div>

        <section class="template-grid" aria-label="分析范本列表">
          <TemplateCard
            v-for="template in filteredTemplates"
            :key="template.id"
            :template="template"
            :selected="template.id === review.selectedTemplateId"
            @select="selectTemplate"
          />
          <p v-if="review.templates.length === 0" class="empty-state">暂无可用范本</p>
          <p v-else-if="filteredTemplates.length === 0" class="empty-state">没有匹配的范本，请尝试其他关键词。</p>
        </section>
      </main>

      <aside class="insight-sidebar">
        <h2>文档洞察</h2>
        <section class="document-preview">
          <div class="document-preview__screen" aria-hidden="true">
            <div class="document-preview__toolbar"></div>
            <div class="document-preview__line document-preview__line--long"></div>
            <div class="document-preview__line"></div>
            <div class="document-preview__highlight"></div>
            <div class="document-preview__line document-preview__line--short"></div>
          </div>
          <strong>{{ review.files[0]?.name || '待上传文档' }}</strong>
          <span>最近上传 · 已就绪</span>
        </section>

        <section class="match-panel">
          <div class="match-panel__label"><span>AI 检测匹配度</span><strong>88% 匹配</strong></div>
          <div class="match-track"><span></span></div>
          <p>根据检测到的条款，AI 建议使用 <b>{{ selectedTemplate?.name }}</b> 范本。</p>
        </section>

        <section class="tip-panel">
          <div class="tip-panel__heading">
            <el-icon aria-hidden="true"><InfoFilled /></el-icon>
            <strong>专业提示</strong>
          </div>
          <p>与自定义规则相比，选择预定义范本可使分析速度提高 400%。</p>
        </section>
      </aside>
    </div>

    <ReviewFooter @previous="goPrevious" @next="goNext">
      选择后将立即开始分析
    </ReviewFooter>
  </div>
</template>

<style scoped>
.review-page {
  width: min(1440px, 100%);
  margin: 0 auto;
}

.page-heading {
  max-width: 760px;
  margin: 0 auto 28px;
  text-align: center;
}

.page-heading h1 {
  margin-bottom: 8px;
  font-size: 36px;
}

.page-heading p {
  margin: 0;
  color: var(--ink-muted);
  font-size: 15px;
  line-height: 1.7;
}

.templates-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 280px;
  align-items: start;
  gap: 28px;
}

.templates-main,
.insight-sidebar {
  min-width: 0;
}

.template-controls {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 24px;
}

.category-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.category-chip {
  min-height: var(--control-height);
  padding: 8px 16px;
  border: 0;
  border-radius: 999px;
  color: var(--ink-muted);
  background: var(--surface-high);
  cursor: pointer;
}

.category-chip:hover,
.category-chip--active {
  color: #ffffff;
  background: var(--action);
}

.template-search {
  display: flex;
  width: min(100%, 300px);
  min-height: var(--control-height);
  align-items: center;
  gap: 8px;
  padding: 0 12px;
  border: 1px solid var(--outline);
  border-radius: var(--radius-md);
  background: var(--surface);
}

.template-search:focus-within {
  box-shadow: var(--focus-ring);
}

.template-search input {
  width: 100%;
  min-width: 0;
  border: 0;
  outline: 0;
  color: var(--ink);
  background: transparent;
}

.template-search .el-icon {
  flex: 0 0 auto;
  color: var(--ink-muted);
  font-size: 20px;
}

.template-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 18px;
}

.empty-state {
  grid-column: 1 / -1;
  margin: 20px 0;
  color: var(--ink-muted);
  text-align: center;
}

.insight-sidebar {
  display: grid;
  gap: 18px;
  padding-left: 24px;
  border-left: 1px solid var(--outline-soft);
}

.insight-sidebar h2 {
  margin: 0;
  font-size: 16px;
}

.document-preview {
  display: grid;
  gap: 7px;
  padding: 12px;
  border: 1px solid var(--outline-soft);
  border-radius: var(--radius-md);
  background: var(--surface);
}

.document-preview__screen {
  display: grid;
  min-height: 145px;
  align-content: start;
  gap: 11px;
  padding: 16px 14px;
  border: 1px solid #adc3df;
  border-radius: var(--radius-sm);
  background: #e9f1fb;
}

.document-preview__toolbar {
  width: 36%;
  height: 10px;
  margin-bottom: 8px;
  border-radius: 2px;
  background: var(--action);
}

.document-preview__line {
  width: 74%;
  height: 6px;
  border-radius: 2px;
  background: #9bb2ce;
}

.document-preview__line--long { width: 90%; }
.document-preview__line--short { width: 56%; }

.document-preview__highlight {
  width: 82%;
  height: 15px;
  border-radius: 2px;
  background: #b9d0fb;
}

.document-preview strong {
  font-size: 13px;
}

.document-preview > span {
  color: var(--ink-muted);
  font-size: 11px;
}

.match-panel {
  display: grid;
  gap: 10px;
}

.match-panel__label {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  color: var(--ink-muted);
  font-size: 12px;
}

.match-panel__label strong {
  color: var(--action);
}

.match-track {
  height: 6px;
  overflow: hidden;
  border-radius: 999px;
  background: var(--action-soft);
}

.match-track span {
  display: block;
  width: 88%;
  height: 100%;
  background: var(--action);
}

.match-panel p,
.tip-panel p {
  margin: 0;
  color: var(--ink-muted);
  font-size: 12px;
  line-height: 1.7;
}

.match-panel b {
  color: var(--ink);
}

.tip-panel {
  margin-top: auto;
  padding: 16px;
  border: 1px solid #a8c5ff;
  border-radius: var(--radius-md);
  background: var(--action-soft);
}

.tip-panel__heading {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  color: var(--action);
  font-size: 12px;
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

@media (max-width: 1100px) {
  .templates-layout {
    grid-template-columns: 1fr;
  }

  .insight-sidebar {
    grid-template-columns: repeat(3, minmax(0, 1fr));
    align-items: start;
    padding: 20px 0 0;
    border-top: 1px solid var(--outline-soft);
    border-left: 0;
  }

  .insight-sidebar h2 {
    grid-column: 1 / -1;
  }

  .tip-panel {
    margin-top: 0;
  }
}

@media (max-width: 760px) {
  .template-controls {
    align-items: stretch;
    flex-direction: column;
  }

  .template-search {
    width: 100%;
  }

  .template-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .insight-sidebar {
    grid-template-columns: 1fr;
  }

  .insight-sidebar h2 {
    grid-column: auto;
  }
}

@media (max-width: 480px) {
  .page-heading h1 {
    font-size: 28px;
  }

  .template-grid {
    grid-template-columns: 1fr;
  }

  .category-chips {
    flex-wrap: nowrap;
    overflow-x: auto;
    padding-bottom: 3px;
  }

  .category-chip {
    flex: 0 0 auto;
  }
}
</style>
