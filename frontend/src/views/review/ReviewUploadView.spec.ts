import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import ReviewUploadView from './ReviewUploadView.vue'
import { useReviewStore } from '@/stores/review'

vi.mock('@/api/review/review', () => ({
  listRules: vi.fn(),
  listTemplates: vi.fn(),
  createRule: vi.fn(),
  createTemplate: vi.fn(),
  createBatch: vi.fn(),
  addBatchDocument: vi.fn(),
  removeBatchDocument: vi.fn(),
  startAnalysis: vi.fn(),
  getAnalysisJob: vi.fn(),
  listFindings: vi.fn(),
  streamAnalysis: vi.fn(),
  decideFinding: vi.fn(),
  decideOverall: vi.fn(),
  createExport: vi.fn(),
}))

vi.mock('@/api/knowledge/docs', () => ({
  uploadDoc: vi.fn(),
}))

import * as reviewApi from '@/api/review/review'
import * as docsApi from '@/api/knowledge/docs'

describe('ReviewUploadView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    vi.mocked(reviewApi.listRules).mockResolvedValue({ data: { items: [], total: 0, page: 1, page_size: 50 } } as never)
    vi.mocked(reviewApi.listTemplates).mockResolvedValue({ data: { items: [], total: 0, page: 1, page_size: 50 } } as never)
  })

  it('starts with an empty queue and moves to the review console', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/review/upload', name: 'review-upload', component: ReviewUploadView },
        { path: '/review/console', name: 'review-console', component: { template: '<div />' } },
      ],
    })
    await router.push('/review/upload')
    await router.isReady()

    const wrapper = mount(ReviewUploadView, { global: { plugins: [router, ElementPlus] } })

    expect(wrapper.get('h1').text()).toBe('上传文档')
    expect(wrapper.text()).not.toContain('从云端导入')
    expect(wrapper.findAll('[data-file-id]')).toHaveLength(0)
    expect(wrapper.get('[data-test="review-next"]')).toBeTruthy()

    await wrapper.get('[data-test="review-next"]').trigger('click')
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(useReviewStore().currentStep).toBe(1)  // 不再有分步推进，直接进入智能审查页
    expect(router.currentRoute.value.name).toBe('review-console')
  })

  it('uploads selected files through the real batch membership flow', async () => {
    vi.mocked(reviewApi.createBatch).mockResolvedValue({
      data: { id: 'batch-1', name: 'b', document_type: '商业合同', ocr_required: false, revision: 0, documents: [] },
    } as never)
    vi.mocked(docsApi.uploadDoc).mockResolvedValue({
      data: { id: 'doc-1', filename: 'Supplier_Agreement.pdf', status: 'ready', stage_label: 'ready', message: '' },
    } as never)
    vi.mocked(reviewApi.addBatchDocument).mockResolvedValue({
      data: { id: 'mem-1', document_id: 'doc-1', document_version_id: 'doc-1', filename: 'Supplier_Agreement.pdf', status: 'ready' },
    } as never)

    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/review/upload', name: 'review-upload', component: ReviewUploadView }],
    })
    await router.push('/review/upload')
    await router.isReady()

    const wrapper = mount(ReviewUploadView, { global: { plugins: [router, ElementPlus] } })
    const input = wrapper.get('input[type="file"]')
    const selected = new File(['demo contract'], 'Supplier_Agreement.pdf', { type: 'application/pdf' })
    Object.defineProperty(input.element, 'files', { configurable: true, value: [selected] })

    await input.trigger('change')
    await new Promise((resolve) => setTimeout(resolve, 0))

    const store = useReviewStore()
    expect(reviewApi.createBatch).toHaveBeenCalled()
    expect(docsApi.uploadDoc).toHaveBeenCalled()
    expect(reviewApi.addBatchDocument).toHaveBeenCalled()
    expect(store.files.some((file) => file.name === 'Supplier_Agreement.pdf')).toBe(true)
  })

  it('removes a file from the queue', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/review/upload', name: 'review-upload', component: ReviewUploadView }],
    })
    await router.push('/review/upload')
    await router.isReady()

    const wrapper = mount(ReviewUploadView, { global: { plugins: [router, ElementPlus] } })
    const store = useReviewStore()
    store.files.push({ id: 'local-1', name: 'a.pdf', size: '1 KB', progress: 100, status: 'ready' })
    await wrapper.vm.$nextTick()

    expect(store.files).toHaveLength(1)

    await wrapper.get('[data-test="remove-file-local-1"]').trigger('click')

    expect(store.files).toHaveLength(0)
  })
})
