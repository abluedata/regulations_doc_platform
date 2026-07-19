import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import ReviewRulesView from './ReviewRulesView.vue'
import { useReviewStore } from '@/stores/review'

describe('ReviewRulesView', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('toggles a clause and adjusts sensitivity', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/review/rules', name: 'review-rules', component: ReviewRulesView }],
    })
    await router.push('/review/rules')
    await router.isReady()

    const wrapper = mount(ReviewRulesView, { global: { plugins: [router, ElementPlus] } })
    const store = useReviewStore()

    expect(wrapper.get('h1').text()).toBe('审查规则与约束配置')
    await wrapper.get('[data-clause-id="payment-terms"] input').setValue(false)
    await wrapper.get('[data-test="sensitivity"]').setValue('72')

    expect(store.clauses.find((item) => item.id === 'payment-terms')?.enabled).toBe(false)
    expect(store.sensitivity).toBe(72)
  })
})
