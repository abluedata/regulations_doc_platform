import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import ReviewUploadView from './ReviewUploadView.vue'
import { useReviewStore } from '@/stores/review'

describe('ReviewUploadView', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('shows the demo queue and moves to template selection', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/review/upload', name: 'review-upload', component: ReviewUploadView },
        { path: '/review/templates', name: 'review-templates', component: { template: '<div />' } },
      ],
    })
    await router.push('/review/upload')
    await router.isReady()

    const wrapper = mount(ReviewUploadView, { global: { plugins: [router, ElementPlus] } })

    expect(wrapper.get('h1').text()).toBe('上传文档')
    expect(wrapper.findAll('[data-file-id]')).toHaveLength(3)
    expect(wrapper.get('[data-test="review-next"]')).toBeTruthy()

    await wrapper.get('[data-test="review-next"]').trigger('click')
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(useReviewStore().currentStep).toBe(2)
    expect(router.currentRoute.value.name).toBe('review-templates')
  })

  it('removes a file from the local demo queue', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/review/upload', name: 'review-upload', component: ReviewUploadView }],
    })
    await router.push('/review/upload')
    await router.isReady()

    const wrapper = mount(ReviewUploadView, { global: { plugins: [router, ElementPlus] } })
    const store = useReviewStore()
    expect(store.files).toHaveLength(3)

    await wrapper.get('[data-test="remove-file-msa-services"]').trigger('click')

    expect(store.files).toHaveLength(2)
    expect(store.files.some((file) => file.id === 'msa-services')).toBe(false)
  })

  it('adds selected local files to the demo queue', async () => {
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

    expect(useReviewStore().files.some((file) => file.name === 'Supplier_Agreement.pdf')).toBe(true)
  })
})
