import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import ReviewRulesView from './ReviewRulesView.vue'
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

describe('ReviewRulesView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    vi.mocked(reviewApi.listTemplates).mockResolvedValue({ data: { items: [], total: 0, page: 1, page_size: 50 } } as never)
    vi.mocked(reviewApi.listRules).mockResolvedValue({
      data: {
        items: [{ id: 'r1', rule_id: 'r1', name: '付款条款', category: 'finance', severity: 'medium', definition: { description: '付款检查' }, status: 'published' }],
        total: 1,
        page: 1,
        page_size: 50,
      },
    } as never)
  })

  it('toggles a clause and adjusts sensitivity', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/review/rules', name: 'review-rules', component: ReviewRulesView }],
    })
    await router.push('/review/rules')
    await router.isReady()

    const wrapper = mount(ReviewRulesView, { global: { plugins: [router, ElementPlus] } })
    await new Promise((resolve) => setTimeout(resolve, 0))

    const store = useReviewStore()

    expect(wrapper.get('h1').text()).toBe('审查规则与约束配置')
    await wrapper.get('[data-clause-id="r1"] input').setValue(false)
    await wrapper.get('[data-test="sensitivity"]').setValue('72')

    expect(store.clauses.find((item) => item.id === 'r1')?.enabled).toBe(false)
    expect(store.sensitivity).toBe(72)
  })

  it('shows detection settings and real preview data without model-tuning placeholders', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/review/rules', name: 'review-rules', component: ReviewRulesView }],
    })
    await router.push('/review/rules')
    await router.isReady()

    const wrapper = mount(ReviewRulesView, { global: { plugins: [router, ElementPlus] } })
    await new Promise((resolve) => setTimeout(resolve, 0))

    // 检测设置小组件保留灵敏度滑块，且绑定真实 store 值
    expect(wrapper.find('.detection-panel').exists()).toBe(true)
    expect(wrapper.get('[data-test="sensitivity"]').attributes('value')).toBe('85')

    // 配置预览使用真实数据（已启用条款 / 灵敏度 / 文件数）
    const preview = wrapper.get('.config-preview')
    expect(preview.text()).toContain('已启用条款')
    expect(preview.text()).toContain('检测灵敏度')
    expect(preview.text()).toContain('批次大小')

    // 模型微调占位面板与假文案全部移除
    expect(wrapper.find('.tuning-panel').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('模型微调')
    expect(wrapper.text()).not.toContain('分析模型')
    expect(wrapper.text()).not.toContain('标记逻辑')
    expect(wrapper.text()).not.toContain('Legal-LLM')
    expect(wrapper.text()).not.toContain('模型就绪状态')
    expect(wrapper.text()).not.toContain('~1.2 分钟')
    expect(wrapper.text()).not.toContain('项激活')
  })

  it('creates a custom rule through the backend', async () => {
    vi.mocked(reviewApi.createRule).mockResolvedValue({
      data: { id: 'r9', rule_id: 'r9', name: '履约保函', category: 'compliance', severity: 'high', definition: {}, status: 'published' },
    } as never)
    vi.mocked(reviewApi.listRules).mockResolvedValue({
      data: {
        items: [{ id: 'r9', rule_id: 'r9', name: '履约保函', category: 'compliance', severity: 'high', definition: { description: '检查保函' }, status: 'published' }],
        total: 1,
        page: 1,
        page_size: 50,
      },
    } as never)

    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/review/rules', name: 'review-rules', component: ReviewRulesView }],
    })
    await router.push('/review/rules')
    await router.isReady()

    const wrapper = mount(ReviewRulesView, { global: { plugins: [router, ElementPlus] } })
    await new Promise((resolve) => setTimeout(resolve, 0))

    await wrapper.find('.custom-rule').trigger('click')
    expect(wrapper.find('.el-dialog').exists()).toBe(true)

    wrapper.find('input[type="text"]').setValue('履约保函')
    await wrapper.find('.create-form').trigger('submit')
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(reviewApi.createRule).toHaveBeenCalledWith(expect.objectContaining({ name: '履约保函' }))
  })
})
