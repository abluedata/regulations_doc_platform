import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { describe, expect, it } from 'vitest'
import ReviewAssistant from './ReviewAssistant.vue'
import type { ReviewRisk } from '@/types'

const risk: ReviewRisk = {
  id: 'unlimited-liability',
  level: 'high',
  section: '第 3.1 节',
  title: '无限制责任',
  description: '该条款取消了间接损害的责任限制。',
  currentText: '总责任上限为 5,000,000 美元。',
  referenceText: '责任上限应为年度合同价值的 1 倍。',
}

describe('ReviewAssistant', () => {
  it('answers a local question with the selected risk context', async () => {
    const wrapper = mount(ReviewAssistant, { props: { risk }, global: { plugins: [ElementPlus] } })

    expect(wrapper.get('[data-test="assistant-context"]').text()).toContain('无限制责任')
    await wrapper.get('[data-test="assistant-input"]').setValue('这项风险为什么重要？')
    const sendButton = wrapper.get('[data-test="assistant-send"]')
    expect(sendButton.attributes('disabled')).toBeUndefined()
    await sendButton.trigger('click')

    const userMessages = wrapper.findAll('[data-role="user"]')
    const assistantMessages = wrapper.findAll('[data-role="assistant"]')
    expect(userMessages.at(-1)?.text()).toContain('这项风险为什么重要？')
    expect(assistantMessages.at(-1)?.text()).toContain('无限制责任')
  })
})
