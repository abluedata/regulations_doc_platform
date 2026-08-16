import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
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

  it('intercepts anchor clicks to prevent SPA navigation', () => {
    const wrapper = mount(SafeMarkdown, {
      props: { content: '查询（www.gsxt.gov.cn）即可 [官方](https://example.com)' },
    })
    const anchors = wrapper.findAll('a')
    expect(anchors.length).toBeGreaterThanOrEqual(1)
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null)
    // 裸网址 autolink（带编码尾字符）：阻止导航且不开新窗口
    const first = anchors[0]!
    const blocked = new MouseEvent('click', { bubbles: true, cancelable: true })
    first.element.dispatchEvent(blocked)
    expect(blocked.defaultPrevented).toBe(true)
    expect(openSpy).not.toHaveBeenCalled()
    // 干净外链：新标签页打开
    const external = anchors[1]!
    const opened = new MouseEvent('click', { bubbles: true, cancelable: true })
    external.element.dispatchEvent(opened)
    expect(opened.defaultPrevented).toBe(true)
    expect(openSpy).toHaveBeenCalledWith('https://example.com', '_blank', 'noopener,noreferrer')
    openSpy.mockRestore()
  })
})
