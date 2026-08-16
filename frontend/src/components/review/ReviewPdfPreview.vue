<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  ArrowLeft,
  ArrowRight,
  Loading,
  RefreshRight,
  Warning,
  ZoomIn,
  ZoomOut,
} from '@element-plus/icons-vue'
import { getDocument, GlobalWorkerOptions, type PDFDocumentProxy } from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import type { ReviewHighlightRect } from '@/types'

GlobalWorkerOptions.workerSrc = workerUrl

const props = withDefaults(
  defineProps<{
    /** 文档 ID，用于拼装 `/api/docs/{docId}/file` 加载原始 PDF */
    docId: string
    /** 展示用文件名 */
    filename?: string
    /** 需要高亮的矩形（仅 currentPage 上的生效；同时用于缩略图风险页标记） */
    highlightRects?: ReviewHighlightRect[]
    /** 全部发现所在页（缩略图风险点标记，不依赖当前选中） */
    riskPages?: number[]
    /** 外部跳页信号：变化时跳到该页（与工具栏翻页共用一套页码状态） */
    activePage?: number | null
    /** 缩放百分比 50–200 */
    scale?: number
    /** 覆盖加载地址（demo/自测用），默认 `/api/docs/{docId}/file` */
    fileUrl?: string
  }>(),
  {
    filename: '',
    highlightRects: () => [],
    riskPages: () => [],
    activePage: null,
    scale: 100,
    fileUrl: '',
  },
)

const emit = defineEmits<{
  'page-change': [page: number]
  loaded: [total: number]
}>()

const MIN_SCALE = 50
const MAX_SCALE = 200
const ZOOM_STEP = 10
/** 测量不到容器宽度时的兜底渲染宽度（happy-dom 等环境） */
const FALLBACK_WIDTH = 800
/** 缩略图渲染宽度（px） */
const THUMB_WIDTH = 96

const loading = ref(false)
const loadError = ref('')
const rendering = ref(false)
const renderError = ref('')
const currentPage = ref(1)
const totalPages = ref(0)
const zoomPercent = ref(clampScale(props.scale))
const renderedOnce = ref(false)
const pageInput = ref('1')
const zoomInput = ref(String(clampScale(props.scale)))

const scrollerRef = ref<HTMLDivElement | null>(null)
const containerRef = ref<HTMLDivElement | null>(null)
const canvasRef = ref<HTMLCanvasElement | null>(null)
const railRef = ref<HTMLElement | null>(null)

let pdfDoc: PDFDocumentProxy | null = null
let renderTask: { cancel: () => void; promise: Promise<unknown> } | null = null
let resizeObserver: ResizeObserver | null = null
let resizeTimer: ReturnType<typeof setTimeout> | null = null
let thumbObserver: IntersectionObserver | null = null
const thumbRefs = new Map<number, HTMLCanvasElement>()
const thumbRendered = new Set<number>()

/** 当前页 canvas 的 CSS 尺寸与页点尺寸（响应式，驱动 overlay 换算） */
const canvasCssWidth = ref(0)
const canvasCssHeight = ref(0)
const pagePtWidth = ref(1)
const pagePtHeight = ref(1)

const apiBase = import.meta.env.VITE_API_BASE || '/api'
const pdfUrl = computed(() => props.fileUrl || `${apiBase}/docs/${props.docId}/file`)

const pageRects = computed(() => props.highlightRects.filter((rect) => rect.page === currentPage.value))
/** 矩形高亮（precision rect/exact） */
const boxRects = computed(() => pageRects.value.filter((rect) => !rect.pageLevel))
/** 页级退化标记（precision page 或无 rect） */
const pageLevelRects = computed(() => pageRects.value.filter((rect) => rect.pageLevel))
/** 存在风险点的页码集合（缩略图标记用）：全部发现页 + 当前选中高亮页 */
const riskPages = computed(() => new Set([...props.riskPages, ...props.highlightRects.map((rect) => rect.page)]))

const canGoPrevious = computed(() => currentPage.value > 1)
const canGoNext = computed(() => totalPages.value > 0 && currentPage.value < totalPages.value)
const pages = computed(() => Array.from({ length: totalPages.value }, (_, index) => index + 1))

function clampScale(value: number) {
  return Math.min(MAX_SCALE, Math.max(MIN_SCALE, Math.round(value)))
}

function clampPage(page: number) {
  if (!Number.isFinite(page)) return 1
  if (totalPages.value > 0) return Math.min(totalPages.value, Math.max(1, Math.round(page)))
  return Math.max(1, Math.round(page))
}

async function loadDocument() {
  if (!props.docId && !props.fileUrl) return
  cancelRender()
  loading.value = true
  loadError.value = ''
  renderError.value = ''
  try {
    await destroyPdf()
    const task = getDocument({ url: pdfUrl.value })
    pdfDoc = await task.promise
    totalPages.value = pdfDoc.numPages
    thumbRendered.clear()
    emit('loaded', pdfDoc.numPages)
    currentPage.value = clampPage(props.activePage || 1)
    syncInputs()
  } catch (err) {
    loadError.value = err instanceof Error ? err.message : 'PDF 加载失败'
  } finally {
    loading.value = false
  }
  // 等 canvas 挂载后再渲染首屏（loading=false 触发 v-else 分支渲染）
  if (pdfDoc) {
    await nextTick()
    await renderPage()
  }
}

function syncInputs() {
  pageInput.value = String(currentPage.value)
  zoomInput.value = String(zoomPercent.value)
}

async function renderPage() {
  if (!pdfDoc || !containerRef.value || !canvasRef.value) return
  cancelRender()
  rendering.value = true
  renderError.value = ''
  try {
    const page = await pdfDoc.getPage(currentPage.value)
    const baseViewport = page.getViewport({ scale: 1 })
    const containerWidth = containerRef.value.clientWidth || FALLBACK_WIDTH
    const zoom = zoomPercent.value / 100
    const cssWidth = Math.max(1, containerWidth * zoom)
    const cssHeight = Math.max(1, baseViewport.height * (cssWidth / baseViewport.width))
    const dpr = typeof window !== 'undefined' ? window.devicePixelRatio || 1 : 1
    const renderScale = (cssWidth / baseViewport.width) * dpr

    const canvas = canvasRef.value
    canvas.width = Math.max(1, Math.floor(baseViewport.width * renderScale))
    canvas.height = Math.max(1, Math.floor(baseViewport.height * renderScale))
    canvas.style.width = `${cssWidth}px`
    canvas.style.height = `${cssHeight}px`

    canvasCssWidth.value = cssWidth
    canvasCssHeight.value = cssHeight
    pagePtWidth.value = baseViewport.width
    pagePtHeight.value = baseViewport.height

    const context = canvas.getContext('2d')
    if (context) {
      const viewport = page.getViewport({ scale: renderScale })
      renderTask = page.render({ canvas, viewport })
      await renderTask.promise
    }
    renderedOnce.value = true
  } catch (err) {
    if ((err as { name?: string })?.name === 'RenderingCancelledException') return
    renderError.value = err instanceof Error ? err.message : '页面渲染失败'
  } finally {
    rendering.value = false
  }
}

function cancelRender() {
  if (renderTask) {
    try {
      renderTask.cancel()
    } catch {
      // 任务可能已完成，忽略取消异常
    }
    renderTask = null
  }
}

async function destroyPdf() {
  cancelRender()
  const doc = pdfDoc
  pdfDoc = null
  if (doc) {
    try {
      await doc.destroy()
    } catch {
      // 销毁失败不影响后续加载
    }
  }
  renderedOnce.value = false
}

function goToPage(page: number) {
  const target = clampPage(page)
  if (target === currentPage.value && renderedOnce.value) return
  currentPage.value = target
  syncInputs()
  emit('page-change', target)
  void renderPage()
  void nextTick(() => {
    railRef.value?.querySelector(`[data-page="${target}"]`)?.scrollIntoView({ block: 'nearest' })
  })
}

function goPrevious() {
  goToPage(currentPage.value - 1)
}

function goNext() {
  goToPage(currentPage.value + 1)
}

function jumpToInput() {
  const parsed = Number.parseInt(pageInput.value, 10)
  if (Number.isFinite(parsed)) goToPage(parsed)
  else syncInputs()
}

function applyZoomInput() {
  const parsed = Number.parseInt(zoomInput.value, 10)
  if (Number.isFinite(parsed)) setZoom(parsed)
  else syncInputs()
}

function setZoom(value: number) {
  const next = clampScale(value)
  if (next === zoomPercent.value) return
  zoomPercent.value = next
  syncInputs()
  void renderPage()
}

function scheduleResizeRender() {
  if (resizeTimer) clearTimeout(resizeTimer)
  resizeTimer = setTimeout(() => { void renderPage() }, 150)
}

/** pdf-pt / normalized-1000 坐标 → canvas px */
function rectStyle(rect: ReviewHighlightRect) {
  let x0: number
  let y0: number
  let x1: number
  let y1: number
  const space = rect.space || 'pdf-pt'
  if (space === 'normalized-1000-top-left') {
    x0 = (rect.x0 / 1000) * canvasCssWidth.value
    y0 = (rect.y0 / 1000) * canvasCssHeight.value
    x1 = (rect.x1 / 1000) * canvasCssWidth.value
    y1 = (rect.y1 / 1000) * canvasCssHeight.value
  } else {
    // 默认 pdf-pt：页点坐标 × (canvas 宽 / 页点宽)
    const k = canvasCssWidth.value / pagePtWidth.value
    x0 = rect.x0 * k
    y0 = rect.y0 * k
    x1 = rect.x1 * k
    y1 = rect.y1 * k
  }
  const left = Math.min(x0, x1)
  const top = Math.min(y0, y1)
  const width = Math.max(2, Math.abs(x1 - x0))
  const height = Math.max(2, Math.abs(y1 - y0))
  return {
    left: `${left}px`,
    top: `${top}px`,
    width: `${width}px`,
    height: `${height}px`,
  }
}

// ── 缩略图栏：懒渲染 ────────────────────────────────────────────

function setThumbRef(page: number) {
  return (element: unknown) => {
    const canvas = element as HTMLCanvasElement | null
    if (canvas) thumbRefs.set(page, canvas)
    else thumbRefs.delete(page)
  }
}

async function renderThumb(page: number) {
  if (!pdfDoc || thumbRendered.has(page)) return
  const canvas = thumbRefs.get(page)
  if (!canvas) return
  thumbRendered.add(page)
  try {
    const pdfPage = await pdfDoc.getPage(page)
    const base = pdfPage.getViewport({ scale: 1 })
    const scale = THUMB_WIDTH / base.width
    const viewport = pdfPage.getViewport({ scale })
    canvas.width = Math.max(1, Math.floor(viewport.width))
    canvas.height = Math.max(1, Math.floor(viewport.height))
    const context = canvas.getContext('2d')
    if (context) await pdfPage.render({ canvas, canvasContext: context, viewport }).promise
  } catch {
    thumbRendered.delete(page)
  }
}

function onThumbVisible(entries: IntersectionObserverEntry[]) {
  for (const entry of entries) {
    if (!entry.isIntersecting) continue
    const page = Number((entry.target as HTMLElement).dataset.page)
    if (Number.isFinite(page)) void renderThumb(page)
  }
}

function setupThumbObserver() {
  if (typeof IntersectionObserver === 'undefined' || !railRef.value) return
  thumbObserver = new IntersectionObserver(onThumbVisible, { root: railRef.value, rootMargin: '120px' })
  for (const target of railRef.value.querySelectorAll('[data-page]')) {
    thumbObserver.observe(target)
  }
}

watch(
  () => props.docId,
  () => { void loadDocument() },
)
watch(
  () => props.fileUrl,
  () => { void loadDocument() },
)
watch(
  () => props.activePage,
  (page) => {
    if (typeof page === 'number' && Number.isFinite(page)) goToPage(page)
  },
)
watch(
  () => props.scale,
  (value) => { setZoom(value) },
)
watch(totalPages, async () => {
  await nextTick()
  thumbObserver?.disconnect()
  setupThumbObserver()
})

onMounted(() => {
  if (typeof ResizeObserver !== 'undefined' && containerRef.value) {
    resizeObserver = new ResizeObserver(scheduleResizeRender)
    resizeObserver.observe(containerRef.value)
  }
  if (props.docId || props.fileUrl) void loadDocument()
})

onBeforeUnmount(() => {
  if (resizeTimer) clearTimeout(resizeTimer)
  resizeObserver?.disconnect()
  thumbObserver?.disconnect()
  cancelRender()
  void destroyPdf()
})

defineExpose({ goToPage, currentPage, totalPages })
</script>

<template>
  <section class="pdf-preview" aria-label="PDF 文档预览">
    <header class="pdf-toolbar">
      <span class="pdf-filename" data-test="pdf-filename">{{ filename || docId }}</span>

      <div class="pdf-toolbar__nav">
        <button
          type="button"
          class="pdf-tool-btn"
          data-test="pdf-prev"
          aria-label="上一页"
          :disabled="!canGoPrevious"
          @click="goPrevious"
        >
          <el-icon aria-hidden="true"><ArrowLeft /></el-icon>
        </button>

        <form class="pdf-page-form" data-test="pdf-page-form" @submit.prevent="jumpToInput">
          <input
            v-model="pageInput"
            class="pdf-page-input"
            data-test="pdf-page-input"
            type="text"
            inputmode="numeric"
            aria-label="页码"
            @blur="jumpToInput"
          />
          <span class="pdf-page-total" data-test="pdf-page-total">/ {{ totalPages }}</span>
        </form>

        <button
          type="button"
          class="pdf-tool-btn"
          data-test="pdf-next"
          aria-label="下一页"
          :disabled="!canGoNext"
          @click="goNext"
        >
          <el-icon aria-hidden="true"><ArrowRight /></el-icon>
        </button>
      </div>

      <div class="pdf-zoom" aria-label="缩放">
        <button
          type="button"
          class="pdf-tool-btn"
          data-test="pdf-zoom-out"
          aria-label="缩小"
          :disabled="zoomPercent <= MIN_SCALE"
          @click="setZoom(zoomPercent - ZOOM_STEP)"
        >
          <el-icon aria-hidden="true"><ZoomOut /></el-icon>
        </button>
        <form class="pdf-zoom-form" data-test="pdf-zoom-form" @submit.prevent="applyZoomInput">
          <input
            v-model="zoomInput"
            class="pdf-zoom-input"
            data-test="pdf-zoom-input"
            type="text"
            inputmode="numeric"
            aria-label="缩放百分比"
            @blur="applyZoomInput"
          />
          <span>%</span>
        </form>
        <button
          type="button"
          class="pdf-tool-btn"
          data-test="pdf-zoom-in"
          aria-label="放大"
          :disabled="zoomPercent >= MAX_SCALE"
          @click="setZoom(zoomPercent + ZOOM_STEP)"
        >
          <el-icon aria-hidden="true"><ZoomIn /></el-icon>
        </button>
      </div>
    </header>

    <div class="pdf-body">
      <nav ref="railRef" class="pdf-thumbnails" aria-label="页面缩略图" data-test="pdf-thumbnails">
        <button
          v-for="page in pages"
          :key="page"
          type="button"
          class="pdf-thumb"
          :class="{ 'pdf-thumb--active': page === currentPage, 'pdf-thumb--risk': riskPages.has(page) }"
          :data-page="page"
          :aria-label="`第 ${page} 页`"
          @click="goToPage(page)"
        >
          <canvas :ref="setThumbRef(page)" class="pdf-thumb__canvas"></canvas>
          <span class="pdf-thumb__label">{{ page }}</span>
          <span v-if="riskPages.has(page)" class="pdf-thumb__badge" data-test="pdf-thumb-risk" aria-hidden="true"></span>
        </button>
      </nav>

      <div ref="scrollerRef" class="pdf-scroller" data-test="pdf-scroller">
        <div v-if="loading" class="pdf-status" data-test="pdf-loading">
          <el-icon class="is-loading" aria-hidden="true"><Loading /></el-icon>
          <span>正在加载 PDF…</span>
        </div>

        <div v-else-if="loadError" class="pdf-status pdf-status--error" data-test="pdf-error" role="alert">
          <el-icon aria-hidden="true"><Warning /></el-icon>
          <p>{{ loadError }}</p>
          <el-button size="small" type="primary" plain data-test="pdf-retry" @click="loadDocument">
            <el-icon aria-hidden="true"><RefreshRight /></el-icon>
            重试
          </el-button>
        </div>

        <template v-else>
          <div ref="containerRef" class="pdf-canvas-wrap">
            <div class="pdf-page-frame" data-test="pdf-page-frame">
              <canvas ref="canvasRef" class="pdf-canvas" data-test="pdf-canvas"></canvas>
              <div class="pdf-overlay" data-test="pdf-overlay" aria-label="证据高亮">
                <div
                  v-for="(rect, index) in boxRects"
                  :key="`rect-${index}`"
                  class="pdf-highlight"
                  data-test="pdf-highlight"
                  :style="rectStyle(rect)"
                ></div>
                <div v-if="pageLevelRects.length" class="pdf-page-flag" data-test="pdf-page-flag">
                  <div class="pdf-page-flag__bar" aria-hidden="true"></div>
                  <span class="pdf-page-flag__badge" data-test="pdf-page-badge">
                    <el-icon aria-hidden="true"><Warning /></el-icon>
                    该页存在风险点
                  </span>
                </div>
              </div>
            </div>
          </div>
          <div v-if="rendering" class="pdf-rendering" data-test="pdf-rendering">正在渲染页面…</div>
          <div v-if="renderError" class="pdf-render-error" role="alert" data-test="pdf-render-error">{{ renderError }}</div>
        </template>
      </div>
    </div>
  </section>
</template>

<style scoped>
.pdf-preview {
  display: flex;
  min-width: 0;
  min-height: 0;
  flex: 1;
  flex-direction: column;
  background: #eef2f8;
}

.pdf-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  min-height: 56px;
  padding: 8px 16px;
  border-bottom: 1px solid var(--outline-soft);
  background: var(--surface);
}

.pdf-filename {
  min-width: 0;
  overflow: hidden;
  color: var(--ink-muted);
  font-size: 13px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pdf-toolbar__nav {
  display: flex;
  align-items: center;
  gap: 8px;
}

.pdf-tool-btn {
  display: inline-flex;
  width: 32px;
  height: 32px;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--outline-soft);
  border-radius: var(--radius-sm);
  color: var(--ink);
  background: var(--surface);
  cursor: pointer;
}

.pdf-tool-btn:hover:not(:disabled) {
  border-color: var(--action);
  color: var(--action);
}

.pdf-tool-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.pdf-page-form {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--ink-muted);
  font-size: 13px;
}

.pdf-page-input {
  width: 44px;
  padding: 4px 6px;
  border: 1px solid var(--outline-soft);
  border-radius: var(--radius-sm);
  text-align: center;
  font-size: 13px;
}

.pdf-page-input:focus {
  border-color: var(--action);
  outline: none;
}

.pdf-zoom {
  display: flex;
  align-items: center;
  gap: 8px;
}

.pdf-zoom-form {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  color: var(--ink-muted);
  font-size: 13px;
}

.pdf-zoom-input {
  width: 44px;
  padding: 4px 6px;
  border: 1px solid var(--outline-soft);
  border-radius: var(--radius-sm);
  text-align: center;
  font-size: 13px;
}

.pdf-zoom-input:focus {
  border-color: var(--action);
  outline: none;
}

.pdf-body {
  display: flex;
  min-height: 0;
  flex: 1;
}

/* 页码缩略图栏（仿法智：左侧竖排缩略图 + 风险页标记） */
.pdf-thumbnails {
  display: flex;
  width: 128px;
  min-width: 128px;
  max-height: 100%;
  flex-direction: column;
  gap: 8px;
  overflow-y: auto;
  padding: 12px 8px;
  border-right: 1px solid var(--outline-soft);
  background: var(--surface);
}

.pdf-thumb {
  position: relative;
  display: flex;
  width: 100%;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  padding: 4px;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  background: transparent;
  cursor: pointer;
}

.pdf-thumb:hover {
  background: var(--surface-low);
}

.pdf-thumb--active {
  border-color: var(--action);
  background: var(--action-soft);
}

.pdf-thumb__canvas {
  width: 100%;
  height: auto;
  border: 1px solid var(--outline-soft);
  border-radius: 2px;
  background: #ffffff;
}

.pdf-thumb__label {
  color: var(--ink-muted);
  font-size: 11px;
  line-height: 1.2;
}

.pdf-thumb--active .pdf-thumb__label {
  color: var(--action);
  font-weight: 700;
}

.pdf-thumb__badge {
  position: absolute;
  top: 8px;
  right: 8px;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--danger, #f56c6c);
}

.pdf-scroller {
  position: relative;
  display: flex;
  min-width: 0;
  min-height: 0;
  flex: 1;
  flex-direction: column;
  overflow: auto;
  padding: 20px;
}

.pdf-status {
  display: grid;
  flex: 1;
  place-items: center;
  align-content: center;
  gap: 10px;
  color: var(--ink-muted);
}

.pdf-status--error {
  color: var(--danger);
}

.pdf-canvas-wrap {
  display: flex;
  min-width: 0;
  flex: 1;
  align-items: flex-start;
  justify-content: center;
}

.pdf-page-frame {
  position: relative;
  box-shadow: 0 2px 12px rgba(31, 45, 80, 0.14);
  background: #ffffff;
}

.pdf-canvas {
  display: block;
}

.pdf-overlay {
  position: absolute;
  inset: 0;
  pointer-events: none;
}

.pdf-highlight {
  position: absolute;
  border: 2px solid rgba(245, 166, 35, 0.9);
  border-radius: 2px;
  background: rgba(245, 166, 35, 0.28);
}

.pdf-page-flag {
  position: absolute;
  right: 10px;
  top: 10px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.pdf-page-flag__bar {
  width: 4px;
  height: 28px;
  border-radius: 2px;
  background: var(--warning, #e6a23c);
}

.pdf-page-flag__badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border-radius: var(--radius-sm);
  color: #ffffff;
  background: var(--warning, #e6a23c);
  font-size: 12px;
}

.pdf-rendering {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  color: var(--ink-muted);
  background: rgba(238, 242, 248, 0.7);
  font-size: 13px;
}

.pdf-render-error {
  padding: 12px;
  color: var(--danger);
  text-align: center;
}
</style>
