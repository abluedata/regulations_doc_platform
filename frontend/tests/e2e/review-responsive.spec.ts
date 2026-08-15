import { expect, test } from '@playwright/test'
import { mkdirSync } from 'node:fs'
import { resolve } from 'node:path'

const viewports = [
  { name: 'desktop-1440', width: 1440, height: 900 },
  { name: 'tablet-1024', width: 1024, height: 768 },
  { name: 'mobile-390', width: 390, height: 844 },
]

for (const viewport of viewports) {
  test(`review console has no page overflow at ${viewport.name}`, async ({ page }) => {
    await page.setViewportSize(viewport)
    await page.goto('/review/console')
    await expect(page.getByRole('heading', { level: 1, name: 'AI 审查分析' })).toBeVisible()
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
    expect(overflow).toBeLessThanOrEqual(1)

    const evidenceDir = resolve('..', 'docs', 'evidence', 'w5', 'screenshots')
    mkdirSync(evidenceDir, { recursive: true })
    await page.screenshot({ path: resolve(evidenceDir, `${viewport.name}.png`), fullPage: true })
  })
}
