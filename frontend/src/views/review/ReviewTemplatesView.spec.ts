import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import ReviewTemplatesView from './ReviewTemplatesView.vue'
import { useReviewStore } from '@/stores/review'

vi.mock('@/api/review', () => ({
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

vi.mock('@/api/docs', () => ({
  uploadDoc: vi.fn(),
}))

import * as reviewApi from '@/api/review'

describe('ReviewTemplatesView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    vi.mocked(reviewApi.listRules).mockResolvedValue({
      data: { items: [], total: 0, page: 1, page_size: 50 },
    } as never)
    vi.mocked(reviewApi.listTemplates).mockResolvedValue({
      data: {
        items: [
          { id: 'tpl-1', name: '服务协议', category: '交易类', description: '服务合同审查范本', rule_version_ids: ['r1'], status: 'published' },
          { id: 'tpl-2', name: '保密协议', category: '交易类', description: 'NDA 审查范本', rule_version_ids: ['r2'], status: 'published' },
        ],
        total: 2,
        page: 1,
        page_size: 50,
      },
    } as never)
  })

  it('selects a template card loaded from the backend', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/review/templates', name: 'review-templates', component: ReviewTemplatesView }],
    })
    await router.push('/review/templates')
    await router.isReady()

    const wrapper = mount(ReviewTemplatesView, { global: { plugins: [router, ElementPlus] } })
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(wrapper.get('h1').text()).toBe('选择分析范本')
    await wrapper.get('[data-template-id="tpl-2"]').trigger('click')

    expect(useReviewStore().selectedTemplateId).toBe('tpl-2')
  })

  it('does not offer custom template creation', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/review/templates', name: 'review-templates', component: ReviewTemplatesView }],
    })
    await router.push('/review/templates')
    await router.isReady()

    const wrapper = mount(ReviewTemplatesView, { global: { plugins: [router, ElementPlus] } })
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(wrapper.find('.custom-template').exists()).toBe(false)
    expect(wrapper.find('.el-dialog').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('创建自定义范本')
  })

  it('shows a neutral empty state when no templates are available', async () => {
    vi.mocked(reviewApi.listTemplates).mockResolvedValue({
      data: { items: [], total: 0, page: 1, page_size: 50 },
    } as never)

    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/review/templates', name: 'review-templates', component: ReviewTemplatesView }],
    })
    await router.push('/review/templates')
    await router.isReady()

    const wrapper = mount(ReviewTemplatesView, { global: { plugins: [router, ElementPlus] } })
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(wrapper.find('.empty-state').text()).toBe('暂无可用范本')
    expect(wrapper.find('.custom-template').exists()).toBe(false)
  })
})
