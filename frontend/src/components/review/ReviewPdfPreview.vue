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
    /** 需要高亮的矩形（仅 currentPage 上的生效） */
    highlightRects?: ReviewHighlightRect[]
    /** 外部跳页信号：变化时跳到该页（与工具栏翻页共用一套页码状态） */
    activePage?: number | null
    /** 缩放百分比 50–200 */
    scale?: number
    /** 覆盖加载地址（demo/自测用），默认 `/api/docs/{docId}/file` */
    fileUrl?: string
  }>(),
  {
    highlightRects: () => [],
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

const loading = ref(false)
const loadError = ref('')
const rendering = ref(false)
const renderError = ref('')
const currentPage = ref(1)
const totalPages = ref(0)
const zoomPercent = ref(clampScale(props.scale))
const renderedOnce = ref(false)

const scrollerRef = ref<HTMLDivElement | null>(null)
const containerRef = ref<HTMLDivElement | null>(null)
const canvasRef = ref<HTMLCanvasElement | null>(null)

let pdfDoc: PDFDocumentProxy | null = null
let renderTask: { cancel: () => void; promise: Promise<unknown> } | null = null
let resizeObserver: ResizeObserver | null = null
let resizeTimer: ReturnType<typeof setTimeout> | null = null
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

const canGoPrevious = computed(() => currentPage.value > 1)
const canGoNext = computed(() => totalPages.value > 0 && currentPage.value < totalPages.value)

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
    emit('loaded', pdfDoc.numPages)
    currentPage.value = clampPage(props.activePage || 1)
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
  emit('page-change', target)
  void renderPage()
}

function goPrevious() {
  goToPage(currentPage.value - 1)
}

function goNext() {
  goToPage(currentPage.value + 1)
}

function setZoom(value: number) {
  const next = clampScale(value)
  if (next === zoomPercent.value) return
  zoomPercent.value = next
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

onMounted(() => {
  if (typeof ResizeObserver !== 'undefined' && containerRef.value) {
    resizeObserver = new ResizeObserver(scheduleResizeRender)
    resizeObserver.observe(containerRef.value)
  }
  if (props.docId || props.fileUrl) void loadDocument()
})

onBeforeUnmount(() => {
  if (resizeTimer) clearTimeout(resizeTimer)
  if (resizeObserver) resizeObserver.disconnect()
  cancelRender()
  void destroyPdf()
})

defineExpose({ goToPage, currentPage, totalPages })
</script>

<template>
  <section class="pdf-preview" aria-label="PDF 文档预览">
    <header class="pdf-toolbar">
      <div class="pdf-pager">
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
        <span class="pdf-page-indicator" data-test="pdf-page-indicator">
          {{ currentPage }}<span class="pdf-page-total"> / {{ totalPages || '–' }}</span>
        </span>
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
        <span class="pdf-zoom-value" data-test="pdf-zoom-value">{{ zoomPercent }}%</span>
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

.pdf-pager,
.pdf-zoom {
  display: flex;
  align-items: center;
  gap: 8px;
}

.pdf-tool-btn {
  display: grid;
  width: 34px;
  height: 34px;
  place-items: center;
  padding: 0;
  border: 1px solid var(--outline-soft);
  border-radius: var(--radius-sm);
  color: var(--ink);
  background: var(--surface);
  cursor: pointer;
}

.pdf-tool-btn:hover:not(:disabled) {
  border-color: var(--action);
  color: var(--action);
  background: var(--action-soft);
}

.pdf-tool-btn:disabled {
  cursor: not-allowed;
  opacity: 0.4;
}

.pdf-page-indicator {
  min-width: 64px;
  color: var(--ink);
  font-size: 13px;
  font-weight: 700;
  text-align: center;
  font-variant-numeric: tabular-nums;
}

.pdf-page-total {
  color: var(--ink-muted);
  font-weight: 600;
}

.pdf-zoom-value {
  min-width: 46px;
  color: var(--ink-muted);
  font-size: 12px;
  text-align: center;
  font-variant-numeric: tabular-nums;
}

.pdf-scroller {
  position: relative;
  min-height: 0;
  flex: 1;
  overflow: auto;
  padding: 20px;
}

.pdf-status {
  display: grid;
  min-height: 280px;
  place-items: center;
  align-content: center;
  gap: 10px;
  color: var(--ink-muted);
  font-size: 13px;
}

.pdf-status .el-icon {
  font-size: 26px;
}

.pdf-status--error {
  color: var(--danger);
}

.pdf-status--error p {
  max-width: 420px;
  margin: 0;
  font-size: 12px;
  line-height: 1.6;
  text-align: center;
}

.pdf-canvas-wrap {
  width: 100%;
  min-height: 120px;
}

.pdf-page-frame {
  position: relative;
  margin: 0 auto;
  border: 1px solid #c4ccd8;
  background: #ffffff;
  box-shadow: var(--shadow-sm);
  overflow: hidden;
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
  border: 2px solid var(--danger);
  border-radius: 2px;
  background: rgba(255, 200, 0, 0.4);
  box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.08);
}

.pdf-page-flag__bar {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 10px;
  background: rgba(255, 200, 0, 0.65);
  border-bottom: 2px solid var(--danger);
}

.pdf-page-flag__badge {
  position: absolute;
  top: 16px;
  right: 12px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 10px;
  border: 1px solid var(--danger-outline);
  border-radius: var(--radius-sm);
  color: var(--danger);
  background: #fff7e6;
  font-size: 11px;
  font-weight: 700;
}

.pdf-rendering,
.pdf-render-error {
  position: absolute;
  top: 12px;
  left: 50%;
  transform: translateX(-50%);
  padding: 6px 12px;
  border-radius: var(--radius-sm);
  color: var(--ink-muted);
  background: var(--surface);
  box-shadow: var(--shadow-sm);
  font-size: 11px;
}

.pdf-render-error {
  color: var(--danger);
}
</style>
