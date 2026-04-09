/**
 * Stress: cycle primary views repeatedly to catch flaky layout / memory issues.
 * Set ZENAF_E2E_NAV_STRESS_ROUNDS (default 8).
 */
import { test, expect } from '@playwright/test'
import { loginIfConfigured } from './helpers'

const NAV_CYCLE = [
  'Home',
  'Perspectives',
  'Vision map',
  'Vision (tables)',
  'Workspace Organizer',
  'Content',
  'Settings',
] as const

test.describe('navigation stress', () => {
  test('round-trip primary nav many times', async ({ page }) => {
    const rounds = Math.min(40, Math.max(1, parseInt(process.env.ZENAF_E2E_NAV_STRESS_ROUNDS || '8', 10) || 8))
    const res = await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 60000 })
    expect(res?.ok() || res?.status() === 304).toBeTruthy()
    await loginIfConfigured(page)
    const nav = page.getByRole('navigation', { name: 'Primary' })
    for (let r = 0; r < rounds; r++) {
      for (const label of NAV_CYCLE) {
        await nav.getByRole('button', { name: label }).click()
        await expect(page.locator('body')).toBeVisible()
      }
    }
  })
})
