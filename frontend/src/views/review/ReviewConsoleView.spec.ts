import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
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

  it('runs the local demo analysis when the console is opened directly', async () => {
    vi.useFakeTimers()
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/review/console', name: 'review-console', component: ReviewConsoleView }],
    })
    await router.push('/review/console')
    await router.isReady()

    const store = useReviewStore()
    const wrapper = mount(ReviewConsoleView, { global: { plugins: [router, ElementPlus] } })
    expect(store.analysisStatus).toBe('running')

    await vi.advanceTimersByTimeAsync(450)
    expect(store.analysisStatus).toBe('complete')

    wrapper.unmount()
    vi.useRealTimers()
  })

  it('renders the console without an internal left navigation panel', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/review/console', name: 'review-console', component: ReviewConsoleView }],
    })
    await router.push('/review/console')
    await router.isReady()

    const wrapper = mount(ReviewConsoleView, { global: { plugins: [router, ElementPlus] } })

    expect(wrapper.find('.document-outline').exists()).toBe(false)
    expect(wrapper.find('.reader-panel').exists()).toBe(true)
    expect(wrapper.find('.findings-panel').exists()).toBe(true)
  })
})
