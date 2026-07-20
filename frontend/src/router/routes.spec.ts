import { describe, expect, it } from 'vitest'
import router from './index'

describe('review routes', () => {
  it('registers the complete four-step workflow', () => {
    expect(
      router
        .getRoutes()
        .filter((route) => route.path.startsWith('/review/'))
        .map((route) => route.path)
        .sort(),
    ).toEqual(['/review/console', '/review/rules', '/review/templates', '/review/upload'])
  })
})
