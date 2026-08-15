import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import SafeMarkdown from './SafeMarkdown.vue'

describe('SafeMarkdown', () => {
  it('removes scripts, event handlers, and javascript links', () => {
    const wrapper = mount(SafeMarkdown, {
      props: {
        content: '<script>alert(1)</script><img src=x onerror=alert(1)><a href="javascript:alert(1)">bad</a><strong>safe</strong>',
        source: 'html',
      },
    })

    expect(wrapper.html()).not.toContain('<script')
    expect(wrapper.html()).not.toContain('onerror')
    expect(wrapper.html()).not.toContain('javascript:')
    expect(wrapper.text()).toContain('safe')
  })

  it('keeps allowlisted markdown links', () => {
    const wrapper = mount(SafeMarkdown, { props: { content: '[official](https://example.com)' } })
    expect(wrapper.find('a').attributes('href')).toBe('https://example.com')
  })
})
