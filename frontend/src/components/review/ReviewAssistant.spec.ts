import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ReviewAssistant from './ReviewAssistant.vue'
import { useReviewStore } from '@/stores/review'

const { createConversation, streamReviewAssistant } = vi.hoisted(() => ({
  createConversation: vi.fn(),
  streamReviewAssistant: vi.fn(),
}))

vi.mock('@/api/review', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/api/review')>(),
  createConversation,
  streamReviewAssistant,
}))

describe('ReviewAssistant', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    createConversation.mockReset().mockResolvedValue({ data: { id: 'conv-1' } })
    streamReviewAssistant.mockReset()
  })

  it('binds the conversation to the selected document membership', async () => {
    const store = useReviewStore()
    store.analysisJobId = 'job-1'
    store.files = [{
      id: 'membership-1', name: '合同.pdf', size: '1 KB', progress: 100, status: 'ready',
      documentId: 'doc-1', documentVersionId: 'v1',
    }]
    streamReviewAssistant.mockImplementation(async (_id, _payload, handlers) => {
      handlers.onToken?.({ content: '付款期限为三十日。' })
      handlers.onDone?.({ refused: false, citations: [{
        citation_id: 'c1', filename: '合同.pdf', document_id: 'doc-1', document_version_id: 'v1',
        block_id: 'b1', quote: '三十日内付款', quote_start: 0, quote_end: 7,
        locator: { kind: 'pdf', page_number: 2 },
      }] })
    })
    const wrapper = mount(ReviewAssistant, { global: { plugins: [ElementPlus] } })

    await wrapper.get('[data-test="assistant-input"]').setValue('付款期限？')
    await wrapper.get('[data-test="assistant-send"]').trigger('click')

    expect(createConversation).toHaveBeenCalledWith('job-1', 'membership-1')
    expect(wrapper.text()).toContain('付款期限为三十日')
    expect(wrapper.text()).toContain('三十日内付款')
    await wrapper.get('[data-test="assistant-citation"]').trigger('click')
    expect(wrapper.emitted('locate')?.[0]?.[0]).toMatchObject({ document_version_id: 'v1' })
  })

  it('renders a grounded refusal without citations', async () => {
    const store = useReviewStore()
    store.analysisJobId = 'job-1'
    store.files = [{ id: 'membership-1', name: '合同.pdf', size: '1 KB', progress: 100, status: 'ready' }]
    streamReviewAssistant.mockImplementation(async (_id, _payload, handlers) => {
      handlers.onToken?.({ content: '当前文档未提供足够依据，无法可靠回答该问题。' })
      handlers.onDone?.({ refused: true, refusal_code: 'no_evidence', citations: [] })
    })
    const wrapper = mount(ReviewAssistant, { global: { plugins: [ElementPlus] } })
    await wrapper.get('[data-test="assistant-input"]').setValue('外部收入？')
    await wrapper.get('[data-test="assistant-send"]').trigger('click')
    expect(wrapper.get('[data-test="assistant-refusal"]').text()).toContain('未提供足够依据')
    expect(wrapper.find('[data-test="assistant-citation"]').exists()).toBe(false)
  })
})
