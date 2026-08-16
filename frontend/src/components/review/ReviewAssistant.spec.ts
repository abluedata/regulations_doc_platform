import { mount, flushPromises } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ReviewAssistant from './ReviewAssistant.vue'
import { useReviewStore } from '@/stores/review'

const { createConversation, streamReviewAssistant } = vi.hoisted(() => ({
  createConversation: vi.fn(),
  streamReviewAssistant: vi.fn(),
}))

vi.mock('@/api/review/review', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/api/review/review')>(),
  createConversation,
  streamReviewAssistant,
}))

describe('ReviewAssistant', () => {
  beforeEach(() => {
    localStorage.clear()
    setActivePinia(createPinia())
    createConversation.mockReset().mockResolvedValue({ data: { id: 'conv-1' } })
    streamReviewAssistant.mockReset()
  })

  it('restores conversation history after reload and reuses persisted conversation id', async () => {
    localStorage.setItem('review-assistant:job-1', JSON.stringify({
      messages: [
        { id: 2, role: 'user', content: '服务期限是多久？' },
        { id: 3, role: 'assistant', content: '服务期限为36个月。' },
      ],
      selectedMembershipId: 'membership-1',
      conversations: { 'membership-1': 'conv-persisted' },
    }))
    const store = useReviewStore()
    store.analysisJobId = 'job-1'
    store.files = [{
      id: 'membership-1', name: '合同.pdf', size: '1 KB', progress: 100, status: 'ready',
      documentId: 'doc-1', documentVersionId: 'v1',
    }]
    streamReviewAssistant.mockImplementation(async (_id, _payload, handlers) => {
      handlers.onToken?.({ content: '追问回答' })
      handlers.onDone?.({ refused: false, citations: [] })
    })

    const wrapper = mount(ReviewAssistant, { global: { plugins: [ElementPlus] } })
    await flushPromises()

    expect(wrapper.text()).toContain('服务期限是多久？')
    expect(wrapper.text()).toContain('服务期限为36个月。')

    await wrapper.get('[data-test="assistant-input"]').setValue('追问')
    await wrapper.get('[data-test="assistant-send"]').trigger('click')
    await flushPromises()

    expect(streamReviewAssistant).toHaveBeenCalledWith('conv-persisted', expect.anything(), expect.anything())
    expect(createConversation).not.toHaveBeenCalled()
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

  it('renders markdown tables in assistant replies', async () => {
    const store = useReviewStore()
    store.analysisJobId = 'job-1'
    store.files = [{
      id: 'membership-1', name: '合同.pdf', size: '1 KB', progress: 100, status: 'ready',
      documentId: 'doc-1', documentVersionId: 'v1',
    }]
    streamReviewAssistant.mockImplementation(async (_id, _payload, handlers) => {
      handlers.onToken?.({ content: '| 项目 | 金额 |\n| --- | --- |\n| 最高投标限价 | 5220000元 |' })
      handlers.onDone?.({ refused: false, citations: [] })
    })
    const wrapper = mount(ReviewAssistant, { global: { plugins: [ElementPlus] } })
    const input = wrapper.get('[data-test="assistant-input"]')
    await input.setValue('最高限价是多少？')
    await wrapper.get('[data-test="assistant-send"]').trigger('click')
    await flushPromises()
    const md = wrapper.findAll('.assistant-message__content').at(-1)
    expect(md?.exists()).toBe(true)
    if (!md) return
    // happy-dom 的 HTML 解析器会丢弃 table 结构标签（真实浏览器保留），
    // 单测断言 markdown 已被解析且单元格文本保留，表格渲染由浏览器 e2e 覆盖。
    expect(md.text()).toContain('5220000元')
    expect(md.text()).toContain('最高投标限价')
    expect(md.html()).not.toContain('| --- |')
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
