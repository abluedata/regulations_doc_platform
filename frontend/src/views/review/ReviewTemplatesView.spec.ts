import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import ReviewTemplatesView from './ReviewTemplatesView.vue'
import { useReviewStore } from '@/stores/review'

describe('ReviewTemplatesView', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('selects a template card', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/review/templates', name: 'review-templates', component: ReviewTemplatesView }],
    })
    await router.push('/review/templates')
    await router.isReady()

    const wrapper = mount(ReviewTemplatesView, { global: { plugins: [router, ElementPlus] } })

    expect(wrapper.get('h1').text()).toBe('选择分析范本')
    await wrapper.get('[data-template-id="services"]').trigger('click')

    expect(useReviewStore().selectedTemplateId).toBe('services')
  })
})
