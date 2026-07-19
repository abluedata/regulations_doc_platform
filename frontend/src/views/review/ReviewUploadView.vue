<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowLeft,
  CircleCheckFilled,
  Clock,
  Close,
  Delete,
  Document,
  DocumentCopy,
  Loading,
  UploadFilled,
} from '@element-plus/icons-vue'
import ReviewFooter from '@/components/review/ReviewFooter.vue'
import ReviewStepper from '@/components/review/ReviewStepper.vue'
import { useReviewStore } from '@/stores/review'
import type { ReviewFile } from '@/types'

const review = useReviewStore()
const router = useRouter()
const route = useRoute()
const fileInput = ref<HTMLInputElement | null>(null)
const batchName = ref('Q3 Legal Review - EMEA')
const documentType = ref('商业合同')
const ocrEnabled = ref(true)

const readyCount = computed(() => review.files.filter((file) => file.status === 'ready').length)

onMounted(() => review.goToStep(Number(route.meta.reviewStep) || 1))

function fileIcon(file: ReviewFile) {
  return file.status === 'uploading' ? DocumentCopy : Document
}

function fileStatusLabel(file: ReviewFile) {
  if (file.status === 'ready') return '就绪'
  if (file.status === 'uploading') return `${file.progress}% 上传中`
  return '排队中'
}

function fileStatusIcon(file: ReviewFile) {
  if (file.status === 'ready') return CircleCheckFilled
  if (file.status === 'uploading') return Loading
  return Clock
}

function browseFiles() {
  fileInput.value?.click()
}

function removeFile(id: string) {
  const index = review.files.findIndex((file) => file.id === id)
  if (index >= 0) review.files.splice(index, 1)
}

async function goNext() {
  review.nextStep()
  await router.push({ name: 'review-templates' })
}

async function goPrevious() {
  review.previousStep()
  await router.push('/')
}
</script>

<template>
  <div class="review-page upload-page">
    <ReviewStepper :current="review.currentStep" />

    <header class="page-heading">
      <div>
        <h1>上传文档</h1>
        <p>添加您希望在此批次中分析的法律文档。</p>
      </div>
      <el-button plain @click="browseFiles">
        <el-icon aria-hidden="true"><DocumentCopy /></el-icon>
        从云端导入
      </el-button>
    </header>

    <div class="upload-layout">
      <main class="upload-main">
        <button class="drop-zone" type="button" @click="browseFiles">
          <span class="drop-zone__icon" aria-hidden="true"><el-icon><UploadFilled /></el-icon></span>
          <strong>拖拽文件至此</strong>
          <span>支持多个 PDF 和 DOCX 文件。每个文件最大 50MB。</span>
          <span class="drop-zone__action">浏览文件</span>
          <input ref="fileInput" type="file" multiple hidden accept=".pdf,.docx" />
        </button>

        <section class="file-queue" aria-labelledby="file-queue-title">
          <div class="section-bar">
            <h2 id="file-queue-title">文件队列</h2>
            <span>已选择 {{ review.files.length }} 个文件</span>
          </div>
          <ul class="file-list">
            <li v-for="file in review.files" :key="file.id" class="file-row" :data-file-id="file.id">
              <span class="file-row__icon" :class="`file-row__icon--${file.status}`" aria-hidden="true">
                <el-icon><component :is="fileIcon(file)" /></el-icon>
              </span>
              <span class="file-row__content">
                <strong>{{ file.name }}</strong>
                <span v-if="file.status === 'uploading'" class="file-progress">
                  <span class="file-progress__track"><span :style="{ width: `${file.progress}%` }"></span></span>
                  <small>{{ file.progress }}%</small>
                </span>
                <small v-else>{{ file.size }} · {{ file.status === 'ready' ? '已完成' : '等待中' }}</small>
              </span>
              <span class="file-row__status" :class="`file-row__status--${file.status}`">
                <el-icon aria-hidden="true"><component :is="fileStatusIcon(file)" /></el-icon>
                {{ fileStatusLabel(file) }}
              </span>
              <button
                class="icon-button file-row__remove"
                type="button"
                :aria-label="`移除 ${file.name}`"
                :data-test="`remove-file-${file.id}`"
                @click="removeFile(file.id)"
              >
                <el-icon aria-hidden="true"><Delete /></el-icon>
              </button>
            </li>
          </ul>
        </section>
      </main>

      <aside class="upload-sidebar">
        <section class="side-panel batch-panel">
          <h2>批次属性</h2>
          <label>
            <span>批次名称</span>
            <input v-model="batchName" type="text" />
          </label>
          <label>
            <span>文档类型</span>
            <select v-model="documentType">
              <option>商业合同</option>
              <option>NDAs / 保密协议</option>
              <option>雇用协议</option>
              <option>知识产权转让</option>
            </select>
          </label>
          <div class="ocr-setting">
            <div>
              <strong>OCR 增强</strong>
              <small>针对扫描文档或低质量图像的高级文本识别。</small>
            </div>
            <label class="switch-control">
              <span class="sr-only">启用 OCR 增强</span>
              <input v-model="ocrEnabled" type="checkbox" />
              <span aria-hidden="true"></span>
            </label>
          </div>
        </section>

        <section class="side-panel quota-panel">
          <h2>使用额度</h2>
          <div class="quota-line"><span>每月页数</span><strong>1,240 / 5,000</strong></div>
          <div class="quota-track"><span></span></div>
          <p>企业方案：无限批次</p>
        </section>

        <section class="insight-panel">
          <div class="insight-panel__title">
            <el-icon aria-hidden="true"><Document /></el-icon>
            <strong>AI 洞察</strong>
          </div>
          <p>批量处理相似法律结构的多个文件（如 NDA 或主服务协议）可将提取准确度提高 24%。</p>
        </section>
      </aside>
    </div>

    <ReviewFooter @previous="goPrevious" @next="goNext">
      已有 {{ readyCount }} 个文件就绪，所有上传均已加密并在本地处理。
    </ReviewFooter>
  </div>
</template>

<style scoped>
.review-page {
  width: min(1440px, 100%);
  margin: 0 auto;
}

.page-heading {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 24px;
}

.page-heading h1 {
  margin-bottom: 6px;
  font-size: 36px;
}

.page-heading p,
.file-row__content small,
.quota-panel p,
.insight-panel p {
  margin: 0;
  color: var(--ink-muted);
}

.upload-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 300px;
  align-items: start;
  gap: 24px;
}

.upload-main,
.upload-sidebar {
  min-width: 0;
}

.upload-sidebar {
  display: grid;
  gap: 16px;
}

.drop-zone {
  display: flex;
  width: 100%;
  min-height: 330px;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 32px;
  border: 2px dashed var(--outline);
  border-radius: var(--radius-md);
  color: var(--ink);
  background: var(--surface);
  cursor: pointer;
  transition: border-color 160ms ease-out, background-color 160ms ease-out;
}

.drop-zone:hover {
  border-color: var(--action);
  background: var(--surface-low);
}

.drop-zone__icon {
  display: grid;
  width: 64px;
  height: 64px;
  place-items: center;
  border-radius: var(--radius-lg);
  color: var(--action);
  background: var(--action-soft);
  font-size: 34px;
}

.drop-zone strong {
  font-size: 20px;
}

.drop-zone > span:not(.drop-zone__icon):not(.drop-zone__action) {
  max-width: 360px;
  color: var(--ink-muted);
  line-height: 1.6;
  text-align: center;
}

.drop-zone__action {
  margin-top: 10px;
  padding: 10px 28px;
  border-radius: var(--radius-sm);
  color: #ffffff;
  background: var(--action);
  font-weight: 700;
}

.file-queue,
.side-panel {
  border: 1px solid var(--outline-soft);
  border-radius: var(--radius-md);
  background: var(--surface);
}

.file-queue {
  margin-top: 24px;
  overflow: hidden;
}

.section-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 16px 20px;
  background: var(--surface-low);
}

.section-bar h2,
.side-panel h2 {
  margin: 0;
  font-size: 14px;
}

.section-bar span {
  color: var(--ink-muted);
  font-size: 12px;
}

.file-list {
  margin: 0;
  padding: 0;
  list-style: none;
}

.file-row {
  display: grid;
  grid-template-columns: 42px minmax(0, 1fr) auto 32px;
  align-items: center;
  gap: 14px;
  min-height: 82px;
  padding: 14px 20px;
  border-top: 1px solid var(--outline-soft);
}

.file-row__icon {
  display: grid;
  width: 42px;
  height: 42px;
  place-items: center;
  border-radius: var(--radius-sm);
  font-size: 21px;
}

.file-row__icon--ready,
.file-row__icon--queued {
  color: var(--danger);
  background: #fff0ee;
}

.file-row__icon--uploading {
  color: var(--action);
  background: var(--action-soft);
}

.file-row__content,
.file-progress {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 4px;
}

.file-row__content strong {
  overflow: hidden;
  font-size: 14px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-progress {
  flex-direction: row;
  align-items: center;
  max-width: 240px;
}

.file-progress__track,
.quota-track {
  display: block;
  height: 7px;
  overflow: hidden;
  border-radius: 999px;
  background: var(--action-soft);
}

.file-progress__track {
  flex: 1;
}

.file-progress__track span,
.quota-track span {
  display: block;
  height: 100%;
  background: var(--action);
}

.file-progress small {
  color: var(--ink-muted);
  font-size: 11px;
}

.file-row__status {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--ink-muted);
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
}

.file-row__status--ready {
  color: var(--success);
}

.file-row__status--uploading {
  color: var(--action);
}

.file-row__status--queued .el-icon {
  animation: spin 1.2s linear infinite;
}

.icon-button {
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

.icon-button:hover {
  color: var(--danger);
  background: #fff0ee;
}

.side-panel {
  padding: 20px;
}

.side-panel h2 {
  margin-bottom: 18px;
  font-size: 16px;
}

.batch-panel {
  display: grid;
  gap: 16px;
}

.batch-panel label:not(.switch-control) {
  display: grid;
  gap: 7px;
}

.batch-panel label > span,
.ocr-setting strong {
  font-size: 12px;
  font-weight: 700;
}

.batch-panel input[type="text"],
.batch-panel select {
  width: 100%;
  min-height: 40px;
  padding: 8px 10px;
  border: 1px solid var(--outline);
  border-radius: var(--radius-sm);
  color: var(--ink);
  background: var(--surface);
}

.ocr-setting {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding-top: 16px;
  border-top: 1px solid var(--outline-soft);
}

.ocr-setting > div {
  display: grid;
  gap: 5px;
}

.ocr-setting small {
  max-width: 180px;
  color: var(--ink-muted);
  font-size: 11px;
  line-height: 1.5;
}

.switch-control {
  position: relative;
  display: block;
  width: 44px;
  height: 24px;
  flex: 0 0 auto;
}

.switch-control input {
  position: absolute;
  opacity: 0;
}

.switch-control > span:last-child {
  display: block;
  width: 100%;
  height: 100%;
  border-radius: 999px;
  background: var(--outline);
  cursor: pointer;
}

.switch-control > span:last-child::after {
  display: block;
  width: 18px;
  height: 18px;
  margin: 3px;
  border-radius: 50%;
  background: #ffffff;
  content: "";
  transition: transform 160ms ease-out;
}

.switch-control input:checked + span {
  background: var(--action);
}

.switch-control input:checked + span::after {
  transform: translateX(20px);
}

.quota-panel {
  background: var(--surface-low);
}

.quota-line {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  color: var(--ink-muted);
  font-size: 12px;
}

.quota-line strong {
  color: var(--ink);
}

.quota-track {
  margin-top: 12px;
}

.quota-track span {
  width: 25%;
  background: var(--ink);
}

.quota-panel p {
  margin-top: 14px;
  text-align: center;
  font-size: 11px;
}

.insight-panel {
  padding: 20px;
  border-radius: var(--radius-md);
  color: #ffffff;
  background: var(--ink);
}

.insight-panel__title {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #ffffff;
}

.insight-panel p {
  margin-top: 12px;
  color: #d6e1f2;
  font-size: 12px;
  line-height: 1.7;
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

@keyframes spin {
  to { transform: rotate(360deg); }
}

@media (max-width: 900px) {
  .upload-layout {
    grid-template-columns: 1fr;
  }

  .upload-sidebar {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .insight-panel {
    grid-column: 1 / -1;
  }
}

@media (max-width: 600px) {
  .page-heading h1 {
    font-size: 28px;
  }

  .page-heading {
    align-items: stretch;
    flex-direction: column;
  }

  .page-heading .el-button {
    align-self: flex-start;
  }

  .drop-zone {
    min-height: 260px;
    padding: 24px 16px;
  }

  .file-row {
    grid-template-columns: 36px minmax(0, 1fr) 32px;
    gap: 10px;
    padding: 12px;
  }

  .file-row__icon {
    width: 36px;
    height: 36px;
  }

  .file-row__status {
    grid-column: 2;
    justify-self: start;
  }

  .file-row__remove {
    grid-column: 3;
    grid-row: 1 / span 2;
  }

  .upload-sidebar {
    grid-template-columns: 1fr;
  }
}

@media (prefers-reduced-motion: reduce) {
  .file-row__status--queued .el-icon {
    animation: none;
  }
}
</style>
