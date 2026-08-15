import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { nextTick } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ReviewPdfPreview from './ReviewPdfPreview.vue'
import type { ReviewHighlightRect } from '@/types'

const mockGetDocument = vi.fn()
const mockDestroy = vi.fn()

vi.mock('pdfjs-dist', () => ({
  getDocument: (...args: unknown[]) => mockGetDocument(...args),
  GlobalWorkerOptions: {},
}))

interface FakePage {
  pageNumber: number
  getViewport: ReturnType<typeof vi.fn>
  render: ReturnType<typeof vi.fn>
}

interface FakePdfDoc {
  numPages: number
  getPage: ReturnType<typeof vi.fn>
  destroy: ReturnType<typeof vi.fn>
  pages: FakePage[]
}

/** 构造一个 612x792pt（US Letter）的模拟 PDF 文档 */
function makePdfDoc(numPages = 5): FakePdfDoc {
  const pages: FakePage[] = Array.from({ length: numPages }, (_, index) => ({
    pageNumber: index + 1,
    getViewport: vi.fn(({ scale }: { scale: number }) => ({ width: 612 * scale, height: 792 * scale })),
    render: vi.fn(() => ({ promise: Promise.resolve() })),
  }))
  return {
    numPages,
    getPage: vi.fn(async (pageNumber: number) => pages[pageNumber - 1]),
    destroy: vi.fn(async () => {
      mockDestroy()
    }),
    pages,
  }
}

function mockPdfResolve(doc: FakePdfDoc) {
  mockGetDocument.mockReturnValue({ promise: Promise.resolve(doc) })
}

function mountPreview(props: Record<string, unknown> = {}) {
  return mount(ReviewPdfPreview, {
    props: { docId: 'doc-1', ...props },
    global: { plugins: [ElementPlus] },
  })
}

async function waitRender() {
  await flushPromises()
  await flushPromises()
}

describe('ReviewPdfPreview', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockPdfResolve(makePdfDoc(5))
  })

  it('loads the PDF, emits loaded(total) and renders the first page', async () => {
    let resolveDoc!: (doc: FakePdfDoc) => void
    mockGetDocument.mockReturnValue({ promise: new Promise<FakePdfDoc>((resolve) => { resolveDoc = resolve }) })
    const wrapper = mountPreview()
    await nextTick()
    expect(wrapper.find('[data-test="pdf-loading"]').exists()).toBe(true)

    resolveDoc(makePdfDoc(5))
    await waitRender()

    expect(mockGetDocument).toHaveBeenCalledWith(expect.objectContaining({ url: '/api/docs/doc-1/file' }))
    expect(wrapper.emitted('loaded')).toEqual([[5]])
    expect(wrapper.find('[data-test="pdf-loading"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="pdf-page-indicator"]').text()).toContain('1')
    expect(wrapper.find('[data-test="pdf-page-indicator"]').text()).toContain('5')
    expect(wrapper.find('[data-test="pdf-canvas"]').exists()).toBe(true)
  })

  it('navigates pages with the toolbar and emits page-change', async () => {
    const wrapper = mountPreview()
    await waitRender()

    expect(wrapper.get('[data-test="pdf-prev"]').attributes('disabled')).toBeDefined()

    await wrapper.get('[data-test="pdf-next"]').trigger('click')
    await flushPromises()

    expect(wrapper.emitted('page-change')?.at(-1)).toEqual([2])
    expect(wrapper.get('[data-test="pdf-page-indicator"]').text()).toContain('2')
    expect(wrapper.get('[data-test="pdf-prev"]').attributes('disabled')).toBeUndefined()

    await wrapper.get('[data-test="pdf-prev"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-test="pdf-page-indicator"]').text()).toContain('1')
  })

  it('jumps to the activePage prop when it changes', async () => {
    const wrapper = mountPreview({ activePage: 1 })
    await waitRender()

    await wrapper.setProps({ activePage: 4 })
    await flushPromises()

    expect(wrapper.emitted('page-change')?.at(-1)).toEqual([4])
    expect(wrapper.get('[data-test="pdf-page-indicator"]').text()).toContain('4')
  })

  it('renders pdf-pt highlight rects scaled to the canvas size', async () => {
    const rects: ReviewHighlightRect[] = [{ page: 1, x0: 115, y0: 529, x1: 877, y1: 601, space: 'pdf-pt' }]
    const wrapper = mountPreview({ highlightRects: rects })
    await waitRender()

    const highlight = wrapper.get('[data-test="pdf-highlight"]')
    // 容器宽回退 800px，页宽 612pt → k = 800/612 ≈ 1.3072；left ≈ 115*k ≈ 150.3
    const style = highlight.attributes('style') || ''
    expect(style).toContain('left: 150.')
    expect(style).toContain('width: 996.')
  })

  it('renders normalized-1000-top-left rects relative to the canvas box', async () => {
    const rects: ReviewHighlightRect[] = [
      { page: 1, x0: 100, y0: 200, x1: 400, y1: 500, space: 'normalized-1000-top-left' },
    ]
    const wrapper = mountPreview({ highlightRects: rects })
    await waitRender()

    const style = wrapper.get('[data-test="pdf-highlight"]').attributes('style') || ''
    // 800px 宽 → x0=80px；高 = 792*(800/612) ≈ 1035.3 → y0 ≈ 207.06
    expect(style).toContain('left: 80px')
    expect(style).toContain('top: 207.')
    expect(style).toContain('width: 240px')
  })

  it('only highlights rects on the current page and swaps them after navigation', async () => {
    const rects: ReviewHighlightRect[] = [
      { page: 1, x0: 0, y0: 0, x1: 50, y1: 20 },
      { page: 2, x0: 0, y0: 0, x1: 80, y1: 30 },
    ]
    const wrapper = mountPreview({ highlightRects: rects })
    await waitRender()

    expect(wrapper.findAll('[data-test="pdf-highlight"]')).toHaveLength(1)
    expect(wrapper.get('[data-test="pdf-highlight"]').attributes('style')).toContain('width: 65.')

    await wrapper.get('[data-test="pdf-next"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-test="pdf-highlight"]').attributes('style')).toContain('width: 104.')
  })

  it('degrades to a page-level banner when precision is page (no rects)', async () => {
    const rects: ReviewHighlightRect[] = [
      { page: 1, x0: 0, y0: 0, x1: 0, y1: 0, space: 'pdf-pt', pageLevel: true },
    ]
    const wrapper = mountPreview({ highlightRects: rects })
    await waitRender()

    expect(wrapper.find('[data-test="pdf-highlight"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="pdf-page-flag"]').exists()).toBe(true)
    expect(wrapper.get('[data-test="pdf-page-badge"]').text()).toContain('该页存在风险点')

    // 翻到无标记的页 → 横条与角标消失
    await wrapper.get('[data-test="pdf-next"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-test="pdf-page-flag"]').exists()).toBe(false)
  })

  it('shows the error state with a working retry button', async () => {
    mockGetDocument.mockReturnValueOnce({ promise: Promise.reject(new Error('network down')) })
    const wrapper = mountPreview()
    await waitRender()

    expect(wrapper.find('[data-test="pdf-error"]').exists()).toBe(true)
    expect(wrapper.get('[data-test="pdf-error"]').text()).toContain('network down')

    // 重试成功
    mockPdfResolve(makePdfDoc(3))
    await wrapper.get('[data-test="pdf-retry"]').trigger('click')
    await waitRender()

    expect(wrapper.find('[data-test="pdf-error"]').exists()).toBe(false)
    expect(wrapper.emitted('loaded')).toEqual([[3]])
  })

  it('adjusts zoom with the toolbar buttons within 50%–200%', async () => {
    const wrapper = mountPreview()
    await waitRender()

    expect(wrapper.get('[data-test="pdf-zoom-value"]').text()).toBe('100%')

    await wrapper.get('[data-test="pdf-zoom-in"]').trigger('click')
    expect(wrapper.get('[data-test="pdf-zoom-value"]').text()).toBe('110%')

    await wrapper.get('[data-test="pdf-zoom-out"]').trigger('click')
    expect(wrapper.get('[data-test="pdf-zoom-value"]').text()).toBe('100%')

    // 放大到 200% 后按钮禁用
    for (let i = 0; i < 12; i += 1) await wrapper.get('[data-test="pdf-zoom-in"]').trigger('click')
    expect(wrapper.get('[data-test="pdf-zoom-value"]').text()).toBe('200%')
    expect(wrapper.get('[data-test="pdf-zoom-in"]').attributes('disabled')).toBeDefined()
  })

  it('uses the fileUrl override when provided', async () => {
    const wrapper = mountPreview({ fileUrl: '/demo.pdf' })
    await waitRender()

    expect(mockGetDocument).toHaveBeenCalledWith(expect.objectContaining({ url: '/demo.pdf' }))
  })

  it('does not load when neither docId nor fileUrl is given', async () => {
    const wrapper = mountPreview({ docId: '' })
    await waitRender()

    expect(mockGetDocument).not.toHaveBeenCalled()
    expect(wrapper.find('[data-test="pdf-loading"]').exists()).toBe(false)
  })

  it('destroys the pdf document on unmount', async () => {
    const doc = makePdfDoc(2)
    mockPdfResolve(doc)
    const wrapper = mountPreview()
    await waitRender()

    wrapper.unmount()
    await flushPromises()

    expect(mockDestroy).toHaveBeenCalled()
  })
})
