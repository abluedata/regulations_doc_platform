import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const mainCss = readFileSync('src/styles/main.css', 'utf8')

describe('shared control sizing', () => {
  it('bridges Element Plus tabs to the responsive control-height token', () => {
    expect(mainCss).toContain('--el-tabs-header-height: var(--control-height)')
  })
})
