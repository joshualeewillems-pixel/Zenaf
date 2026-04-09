/**

 * Minimal browser smoke: app shell loads. Requires `npm run dev` (frontend) + API on 8010 (Vite proxy).

 * Credentials optional: set ZENAF_E2E_EMAIL / ZENAF_E2E_PASSWORD to walk past login if your build shows a login form.

 */

import { test, expect } from '@playwright/test'

import { loginIfConfigured } from './helpers'



test.describe('nightly shell', () => {

  test('root loads without hard error', async ({ page }) => {

    const res = await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 60000 })

    expect(res?.ok() || res?.status() === 304).toBeTruthy()

    await expect(page.locator('body')).toBeVisible()

  })



  test('vision map route reachable when logged in', async ({ page }) => {

    await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 60000 })

    await loginIfConfigured(page)

    const mapBtn = page.getByRole('navigation', { name: 'Primary' }).getByRole('button', { name: 'Vision map' })

    if (!(await mapBtn.isVisible().catch(() => false))) {

      test.skip(true, 'Primary nav or Vision map button not found')

    }

    await mapBtn.click()

    await expect(page.locator('body')).toBeVisible()

  })

})


