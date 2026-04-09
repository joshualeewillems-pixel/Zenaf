/**
 * Section B — Fringe / boundary probes (“define current limits”)
 *
 * PASS = stable, graceful UI. BOUNDARY = partial product behavior documented via annotations
 * (see helpers/outcomes.ts attachments in Playwright HTML + JSON report). FAIL = hard expect.
 */
import { test, expect } from '@playwright/test'
import { loginIfConfigured, openAppLoggedIn } from './helpers'
import { classify, createPageErrorSink, detachPageErrorSink } from './helpers/outcomes'

test.describe.configure({ timeout: 120_000 })

test.describe('B1 Sparse / weak context stability', () => {
  test('triad navigation stays stable (no uncaught errors)', async ({ page }, testInfo) => {
    await openAppLoggedIn(page)
    const { messages, handler } = createPageErrorSink(page)

    await page.getByRole('navigation', { name: 'Primary' }).getByRole('button', { name: 'Vision map' }).click()
    const nodes = page.locator('.react-flow__node')
    await nodes.first().waitFor({ state: 'visible', timeout: 45_000 })
    await nodes.first().click()

    const inspector = page.getByTestId('vision-map-inspector')
    const triadPanel = inspector.getByTestId('map-triad-inspector')

    try {
      for (const seg of [/Water/i, /Soil/i, /Fruit/i] as const) {
        await inspector.getByRole('button', { name: seg }).first().click()
        await expect(triadPanel).toBeVisible()
      }

      if (await inspector.getByText('Map data is still loading').isVisible().catch(() => false)) {
        await classify(testInfo, 'BOUNDARY', 'Inspector showed loading/sync fallback copy — acceptable weak-context state.', {
          screenshot: page,
        })
      }

      expect(messages, `pageerror: ${messages.join(' | ')}`).toEqual([])
    } finally {
      detachPageErrorSink(page, handler)
    }
  })
})

test.describe('B2 Repeated triad segment', () => {
  test('same segment clicks do not explode input length (no spam)', async ({ page }) => {
    await openAppLoggedIn(page)
    await page.getByRole('navigation', { name: 'Primary' }).getByRole('button', { name: 'Vision map' }).click()
    const nodes = page.locator('.react-flow__node')
    await nodes.first().waitFor({ state: 'visible', timeout: 45_000 })
    await nodes.first().click()

    const inspector = page.getByTestId('vision-map-inspector')
    const waterBtn = inspector.getByRole('button', { name: /Water/i }).first()
    const councilInput = page.getByTestId('council-question-input')

    for (let i = 0; i < 8; i++) {
      await waterBtn.click()
    }
    const v = await councilInput.inputValue()
    expect(v.length).toBeLessThan(25_000)
    const chunks = v.split(/\n/).map((s) => s.trim()).filter(Boolean)
    const uniq = new Set(chunks)
    expect(uniq.size).toBeGreaterThan(0)
  })
})

test.describe('B3 Prompt pacing (defer vs chat reinjection)', () => {
  test('after defer + reload, document whether chat prompt still reinjects', async ({ page }, testInfo) => {
    await openAppLoggedIn(page)
    await page.getByRole('navigation', { name: 'Primary' }).getByRole('button', { name: 'Vision map' }).click()
    const nodes = page.locator('.react-flow__node')
    await nodes.first().waitFor({ state: 'visible', timeout: 45_000 }).catch(() => {})
    if ((await nodes.count()) > 0) await nodes.first().click()

    const strip = page.getByTestId('system-prompt-actions')
    if (!(await strip.isVisible({ timeout: 20_000 }).catch(() => false))) {
      await classify(testInfo, 'BOUNDARY', 'No prompt visible to defer — pacing probe skipped (not a failure).')
      test.skip(true, 'No prompt to defer')
    }

    await strip.getByRole('button', { name: 'Remind me later' }).click()
    await strip.getByRole('button', { name: /Later.*4h/i }).click()

    await page.reload({ waitUntil: 'domcontentloaded' })
    await loginIfConfigured(page)
    await page.getByRole('navigation', { name: 'Primary' }).getByRole('button', { name: 'Vision map' }).click()
    await nodes.first().waitFor({ state: 'visible', timeout: 45_000 }).catch(() => {})
    if ((await nodes.count()) > 0) await nodes.first().click()

    const again = page.getByTestId('system-prompt-actions')
    const resurfaced = await again.isVisible({ timeout: 15_000 }).catch(() => false)
    if (resurfaced) {
      await classify(
        testInfo,
        'BOUNDARY',
        'After defer + reload, developmental guide actions visible again — defer does not gate chat reinjection (only dismiss does in current product).',
        { screenshot: page },
      )
    } else {
      await classify(testInfo, 'PASS', 'After defer + reload, system-prompt-actions did not reappear within window (strict non-resurface).')
    }

    const reminderHeading = page.getByTestId('vision-map-inspector').getByTestId('prompt-reminders-heading')
    const remindersVisible = await reminderHeading.isVisible({ timeout: 20_000 }).catch(() => false)
    if (remindersVisible) {
      await classify(testInfo, 'PASS', 'Deferred prompt appears in inspector reminder list after defer (API returned rows).')
    } else {
      await classify(
        testInfo,
        'BOUNDARY',
        'Reminder block not rendered (empty deferred list, API lag, or offline) — UI should stay stable; heading only mounts when fetchDeferredPrompts returns items.',
        { screenshot: page },
      )
    }
  })
})

test.describe('B4 Dismiss suppression', () => {
  test('after dismiss + reload, prompt strip does not immediately return', async ({ page }) => {
    await openAppLoggedIn(page)
    await page.getByRole('navigation', { name: 'Primary' }).getByRole('button', { name: 'Vision map' }).click()
    const nodes = page.locator('.react-flow__node')
    await nodes.first().waitFor({ state: 'visible', timeout: 45_000 }).catch(() => {})
    if ((await nodes.count()) > 0) await nodes.first().click()

    const strip = page.getByTestId('system-prompt-actions')
    test.skip(!(await strip.isVisible({ timeout: 25_000 }).catch(() => false)), 'No prompt to dismiss')

    await strip.getByRole('button', { name: 'Dismiss' }).click()
    await expect(strip).toHaveCount(0)

    await page.reload({ waitUntil: 'domcontentloaded' })
    await loginIfConfigured(page)
    await page.getByRole('navigation', { name: 'Primary' }).getByRole('button', { name: 'Vision map' }).click()
    await nodes.first().waitFor({ state: 'visible', timeout: 45_000 }).catch(() => {})
    if ((await nodes.count()) > 0) await nodes.first().click()

    const after = page.getByTestId('system-prompt-actions')
    await expect(after).toBeHidden({ timeout: 15_000 })
  })
})

test.describe('B5 Auth-gated / partial surface', () => {
  test('/studio non-admin shows clear denied state (not broken chrome)', async ({ page }, testInfo) => {
    await openAppLoggedIn(page)
    await page.goto('/studio', { waitUntil: 'domcontentloaded', timeout: 30_000 })

    const denied = page.getByTestId('studio-admin-denied')
    const ready = page.getByRole('heading', { name: 'Zenaf Studio' }).filter({ hasText: 'Zenaf Studio' })

    if (await denied.isVisible().catch(() => false)) {
      await expect(denied.getByText(/requires admin access/i)).toBeVisible()
      await classify(testInfo, 'PASS', 'Studio correctly gates non-admin with explicit copy.')
      return
    }

    if (await ready.first().isVisible().catch(() => false)) {
      await classify(
        testInfo,
        'BOUNDARY',
        'Studio loaded as ready — current user appears admin-capable; denied path not exercised.',
        { screenshot: page },
      )
      return
    }

    await expect(page.getByText(/loading studio/i)).toBeHidden({ timeout: 30_000 }).catch(() => {})
    const loginGate = page.locator('input[type="email"]').first()
    if (await loginGate.isVisible().catch(() => false)) {
      await classify(testInfo, 'BOUNDARY', 'Studio shows login gate (session not propagated to /studio in this run).')
      return
    }

    throw new Error('Studio surface: unexpected state (not denied, not ready, not login)')
  })
})
