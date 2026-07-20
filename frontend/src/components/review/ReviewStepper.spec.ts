import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ReviewStepper from './ReviewStepper.vue'

describe('ReviewStepper', () => {
  it('marks completed, active and upcoming steps', () => {
    const wrapper = mount(ReviewStepper, { props: { current: 3 } })
    expect(wrapper.findAll('[data-state="complete"]')).toHaveLength(2)
    expect(wrapper.findAll('[data-state="active"]')).toHaveLength(1)
    expect(wrapper.findAll('[data-state="upcoming"]')).toHaveLength(1)
  })
})
