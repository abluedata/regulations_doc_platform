import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import ReviewConsoleView from './ReviewConsoleView.vue'
import { useReviewStore } from '@/stores/review'

describe('ReviewConsoleView', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('approves a completed demo analysis', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/review/console', name: 'review-console', component: ReviewConsoleView }],
    })
    await router.push('/review/console')
    await router.isReady()

    const store = useReviewStore()
    store.startAnalysis()
    store.completeAnalysis()
    const wrapper = mount(ReviewConsoleView, { global: { plugins: [router, ElementPlus] } })

    expect(wrapper.get('h1').text()).toBe('AI 审查分析')
    await wrapper.get('[data-test="approve-draft"]').trigger('click')

    expect(store.analysisStatus).toBe('approved')
  })

  it('disables approval while the demo analysis is running', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/review/console', name: 'review-console', component: ReviewConsoleView }],
    })
    await router.push('/review/console')
    await router.isReady()

    const store = useReviewStore()
    store.startAnalysis()
    const wrapper = mount(ReviewConsoleView, { global: { plugins: [router, ElementPlus] } })

    expect(wrapper.get('[data-test="approve-draft"]').attributes('disabled')).toBeDefined()
  })
})
