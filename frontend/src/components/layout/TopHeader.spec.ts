import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { describe, expect, it } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import indexHtml from '../../../index.html?raw'
import TopHeader from './TopHeader.vue'

describe('product branding', () => {
  it('uses 审核智规 in the document title and application header', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/', component: { template: '<div />' } }],
    })
    await router.push('/')
    await router.isReady()

    const wrapper = mount(TopHeader, {
      props: { menuOpen: false },
      global: { plugins: [router, ElementPlus] },
    })
    expect(indexHtml).toContain('<title>审核智规</title>')
    expect(wrapper.get('.product-brand__copy strong').text()).toBe('审核智规')
    expect(wrapper.get('.product-brand').attributes('aria-label')).toBe('审核智规首页')
  })
})
