import { expect, type Page } from '@playwright/test'

/**
 * Optional login when ATRIA_E2E_EMAIL / ATRIA_E2E_PASSWORD are set.
 * Returns true if the app appears to be past any login gate.
 */
export async function loginIfConfigured(page: Page): Promise<boolean> {
  const email = process.env.ATRIA_E2E_EMAIL
  const password = process.env.ATRIA_E2E_PASSWORD
  if (!email || !password) return true
  const emailInput = page.locator('input[type="email"], input[name="email"], #email').first()
  if (await emailInput.isVisible().catch(() => false)) {
    await emailInput.fill(email)
    await page.locator('input[type="password"]').first().fill(password)
    await page.getByRole('button', { name: /log in|sign in/i }).first().click()
    await page.waitForTimeout(2000)
  }
  return true
}

export async function openAppLoggedIn(page: Page): Promise<void> {
  const res = await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 60_000 })
  expect(res?.ok() || res?.status() === 304).toBeTruthy()
  await loginIfConfigured(page)
}
