import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ReviewAssistant from './ReviewAssistant.vue'
import { useReviewStore } from '@/stores/review'

const api = vi.hoisted(() => ({
  getReviewConversation: vi.fn(),
  listReviewConversationMessages: vi.fn(),
  regenerateReviewRecommendations: vi.fn(),
  clearReviewConversationMessages: vi.fn(),
  streamReviewAssistant: vi.fn(),
}))

vi.mock('@/api/review/review', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/api/review/review')>(),
  ...api,
}))

const persistedMessages = [
  { id: 'message-1', role: 'user', content: '服务期限是多久？', status: 'completed', citations: [] },
  { id: 'message-2', role: 'assistant', content: '服务期限为36个月。', status: 'completed', citations: [] },
]

function seedStore() {
  const store = useReviewStore()
  store.analysisJobId = 'job-1'
  store.files = [{
    id: 'membership-1', name: '合同.pdf', size: '1 KB', progress: 100, status: 'ready',
    documentId: 'doc-1', documentVersionId: 'version-1',
  }]
  return store
}

function snapshot(messages = persistedMessages) {
  return {
    data: {
      conversation: { id: 'conversation-1', job_id: 'job-1', document_id: 'doc-1', document_version_id: 'version-1' },
      messages,
      recommended_questions: [
        { id: 'question-1', question: '付款期限是否存在风险？', rank: 1 },
        { id: 'question-2', question: '违约责任如何调整？', rank: 2 },
      ],
    },
  }
}

describe('ReviewAssistant', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    Object.values(api).forEach((mock) => mock.mockReset())
    api.getReviewConversation.mockResolvedValue(snapshot())
    api.listReviewConversationMessages.mockResolvedValue({ data: { items: persistedMessages } })
    api.clearReviewConversationMessages.mockResolvedValue({ data: undefined })
    api.streamReviewAssistant.mockImplementation(async (_id, _payload, handlers) => {
      handlers.onToken?.({ request_id: 'request-1', content: '流式暂存内容' })
      handlers.onDone?.({ request_id: 'request-1', answer: '服务端终版回答', refused: false, citations: [] })
    })
  })

  it('loads the document-version conversation and renders durable messages and recommendations', async () => {
    const getItem = vi.spyOn(Storage.prototype, 'getItem')
    const setItem = vi.spyOn(Storage.prototype, 'setItem')
    seedStore()

    const wrapper = mount(ReviewAssistant, { global: { plugins: [ElementPlus] } })
    await flushPromises()

    expect(api.getReviewConversation).toHaveBeenCalledWith('job-1', 'version-1')
    expect(wrapper.text()).toContain('服务期限是多久？')
    expect(wrapper.text()).toContain('服务期限为36个月。')
    expect(wrapper.text()).toContain('付款期限是否存在风险？')
    expect(wrapper.text()).not.toContain('与标准模板有什么差异？')
    expect(getItem).not.toHaveBeenCalledWith(expect.stringMatching(/^review-assistant:/))
    expect(setItem).not.toHaveBeenCalledWith(expect.stringMatching(/^review-assistant:/), expect.anything())
    getItem.mockRestore()
    setItem.mockRestore()
  })

  it('reuses the snapshot conversation and reconciles messages after a terminal event', async () => {
    seedStore()
    const wrapper = mount(ReviewAssistant, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    api.listReviewConversationMessages.mockResolvedValueOnce({ data: { items: [
      ...persistedMessages,
      { id: 'message-3', role: 'user', content: '追问', status: 'completed', citations: [] },
      { id: 'message-4', role: 'assistant', content: '服务端终版回答', status: 'completed', citations: [] },
    ] } })

    await wrapper.get('[data-test="assistant-input"]').setValue('追问')
    await wrapper.get('[data-test="assistant-send"]').trigger('click')
    await flushPromises()

    expect(api.streamReviewAssistant).toHaveBeenCalledWith('conversation-1', expect.objectContaining({
      message: '追问',
      finding_id: undefined,
    }), expect.anything())
    expect(api.listReviewConversationMessages).toHaveBeenCalledWith('conversation-1')
    expect(wrapper.text()).toContain('服务端终版回答')
  })

  it('reconciles authoritative messages when the stream connection fails', async () => {
    seedStore()
    api.streamReviewAssistant.mockRejectedValueOnce(new Error('network'))
    api.listReviewConversationMessages.mockResolvedValueOnce({ data: { items: [
      ...persistedMessages,
      { id: 'message-error', role: 'assistant', content: '请求中断，请重试。', status: 'error', citations: [] },
    ] } })
    const wrapper = mount(ReviewAssistant, { global: { plugins: [ElementPlus] } })
    await flushPromises()

    await wrapper.get('[data-test="assistant-input"]').setValue('追问')
    await wrapper.get('[data-test="assistant-send"]').trigger('click')
    await flushPromises()

    expect(api.listReviewConversationMessages).toHaveBeenCalledWith('conversation-1')
    expect(wrapper.text()).toContain('请求中断，请重试。')
  })

  it('shows an empty state when no ready document is available', async () => {
    const store = useReviewStore()
    store.analysisJobId = 'job-1'
    const wrapper = mount(ReviewAssistant, { global: { plugins: [ElementPlus] } })
    await flushPromises()

    expect(api.getReviewConversation).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('尚未关联可问答文档')
    expect(wrapper.get('[data-test="assistant-send"]').attributes('disabled')).toBeDefined()
  })

  it('shows a recoverable error when loading the server conversation fails', async () => {
    seedStore()
    api.getReviewConversation.mockRejectedValueOnce(new Error('offline'))
    const wrapper = mount(ReviewAssistant, { global: { plugins: [ElementPlus] } })
    await flushPromises()

    expect(wrapper.text()).toContain('加载对话失败')
  })

  it('clears persisted messages through the API and reloads them', async () => {
    seedStore()
    const wrapper = mount(ReviewAssistant, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    api.listReviewConversationMessages.mockResolvedValueOnce({ data: { items: [] } })

    await wrapper.get('[aria-label="清空问答记录"]').trigger('click')
    await flushPromises()

    expect(api.clearReviewConversationMessages).toHaveBeenCalledWith('conversation-1')
    expect(api.listReviewConversationMessages).toHaveBeenCalledWith('conversation-1')
    expect(wrapper.text()).not.toContain('服务期限为36个月。')
  })
})
