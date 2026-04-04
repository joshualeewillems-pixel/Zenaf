/**
 * Primary navigation user flows (logged-in shell). Matches App.tsx nav labels.
 * Requires dev server + API; credentials optional via ATRIA_E2E_EMAIL / ATRIA_E2E_PASSWORD.
 */
import { test, expect } from '@playwright/test'
import { loginIfConfigured } from './helpers'

const primaryNav = [
  'Home',
  'Perspectives',
  'Vision map',
  'Vision (tables)',
  'Workspace Organizer',
  'Content',
  'Settings',
] as const

test.describe('primary navigation flows', () => {
  test.beforeEach(async ({ page }) => {
    const res = await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 60000 })
    expect(res?.ok() || res?.status() === 304).toBeTruthy()
    await loginIfConfigured(page)
  })

  for (const label of primaryNav) {
    test(`nav: ${label}`, async ({ page }) => {
      await page.getByRole('navigation', { name: 'Primary' }).getByRole('button', { name: label }).click()
      await expect(page.locator('body')).toBeVisible()
      await expect(page.getByRole('heading', { name: /Atria/ })).toBeVisible()
    })
  }
})
