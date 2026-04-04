/**
 * Section A — Core interaction tests (“should work”)
 *
 * Vision Map triad + council prefill, developmental prompt actions, VE evaluate dismiss,
 * and a partial-capability stub action (Distill) on a focused VE field.
 *
 * Prompt product note: Discuss, Remind me later, and Dismiss cannot all consume the same
 * prompt instance (Remind/Dismiss hide the action strip). The three tests below each prove
 * one primary interaction path; together they cover the matrix.
 */
import { test, expect } from '@playwright/test'
import { openAppLoggedIn } from './helpers'

test.describe.configure({ timeout: 120_000 })

test.describe('A1 Vision Map interaction', () => {
  test('inspector, selected label, and council prefill track Soil / Water / Fruit', async ({ page }) => {
    await openAppLoggedIn(page)
    await page.getByRole('navigation', { name: 'Primary' }).getByRole('button', { name: 'Vision map' }).click()

    const nodes = page.locator('.react-flow__node')
    await nodes.first().waitFor({ state: 'visible', timeout: 45_000 })
    await nodes.first().click()

    const inspector = page.getByTestId('vision-map-inspector')
    const title = inspector.getByTestId('vision-map-selected-title')
    await expect(title).not.toHaveText(/^Vision map$/)

    const labelAfterSelect = (await title.textContent())?.trim() ?? ''
    expect(labelAfterSelect.length).toBeGreaterThan(0)

    const triadPanel = inspector.getByTestId('map-triad-inspector')
    const councilInput = page.getByTestId('council-question-input')
    await expect(councilInput).toBeEnabled()

    await inspector.getByRole('button', { name: /Water/i }).first().click()
    await expect(triadPanel).toHaveAttribute('data-section', 'water')
    await expect(inspector.getByText('What is feeding this row')).toBeVisible()
    const afterWater = await councilInput.inputValue()
    expect(afterWater.trim().length).toBeGreaterThan(10)

    await inspector.getByRole('button', { name: /Soil/i }).first().click()
    await expect(triadPanel).toHaveAttribute('data-section', 'soil')
    await expect(inspector.getByText('Definition, context, and grounding')).toBeVisible()
    const afterSoil = await councilInput.inputValue()
    expect(afterSoil).not.toBe(afterWater)

    await inspector.getByRole('button', { name: /Fruit/i }).first().click()
    await expect(triadPanel).toHaveAttribute('data-section', 'fruit')
    await expect(inspector.getByText('What has emerged or must ship')).toBeVisible()
    const afterFruit = await councilInput.inputValue()
    expect(afterFruit).not.toBe(afterSoil)
    await expect(councilInput).toBeEnabled()

    await expect(title).toHaveText(labelAfterSelect)

    const bestNext = inspector.getByTestId('map-best-next-step')
    if (await bestNext.isVisible().catch(() => false)) {
      await inspector.getByRole('button', { name: /Soil/i }).first().click()
      expect(((await bestNext.textContent()) ?? '').trim().length).toBeGreaterThan(5)
      await inspector.getByRole('button', { name: /Fruit/i }).first().click()
      expect(((await bestNext.textContent()) ?? '').trim().length).toBeGreaterThan(5)
    }
  })
})

test.describe('A2 Prompt interaction', () => {
  test('Discuss → council field focused and prefilled', async ({ page }) => {
    await openAppLoggedIn(page)
    await page.getByRole('navigation', { name: 'Primary' }).getByRole('button', { name: 'Vision map' }).click()
    const nodes = page.locator('.react-flow__node')
    await nodes.first().waitFor({ state: 'visible', timeout: 45_000 }).catch(() => {})
    if ((await nodes.count()) > 0) await nodes.first().click()

    const bar = page.getByTestId('guide-notification-stack-bar')
    test.skip(!(await bar.isVisible({ timeout: 25_000 }).catch(() => false)), 'No stacked guide bar visible')
    await bar.click()
    await page.getByTestId('guide-notification-row').first().click()

    const strip = page.getByTestId('system-prompt-actions')
    await expect(strip).toBeVisible({ timeout: 15_000 })

    await strip.getByRole('button', { name: 'Discuss' }).click()
    const q = page.getByTestId('council-question-input')
    await expect(q).toBeFocused()
    expect((await q.inputValue()).trim().length).toBeGreaterThan(20)
  })

  test('Remind me later → reminder in map inspector (workspace scope)', async ({ page }) => {
    await openAppLoggedIn(page)
    await page.getByRole('navigation', { name: 'Primary' }).getByRole('button', { name: 'Vision map' }).click()
    const nodes = page.locator('.react-flow__node')
    await nodes.first().waitFor({ state: 'visible', timeout: 45_000 }).catch(() => {})
    if ((await nodes.count()) > 0) await nodes.first().click()

    const bar = page.getByTestId('guide-notification-stack-bar')
    test.skip(!(await bar.isVisible({ timeout: 25_000 }).catch(() => false)), 'No guide notification stack for defer')
    await bar.click()
    await page.getByTestId('guide-notification-row').first().click()

    const strip = page.getByTestId('system-prompt-actions')
    await expect(strip).toBeVisible({ timeout: 15_000 })

    await strip.getByRole('button', { name: 'Remind me later' }).click()
    await strip.getByRole('button', { name: /Later.*4h/i }).click()

    const inspector = page.getByTestId('vision-map-inspector')
    await expect(inspector.getByTestId('prompt-reminders-heading')).toBeVisible({ timeout: 15_000 })
  })

  test('Dismiss → prompt action strip removed (suppressed for this snapshot)', async ({ page }) => {
    await openAppLoggedIn(page)
    await page.getByRole('navigation', { name: 'Primary' }).getByRole('button', { name: 'Vision map' }).click()
    const nodes = page.locator('.react-flow__node')
    await nodes.first().waitFor({ state: 'visible', timeout: 45_000 }).catch(() => {})
    if ((await nodes.count()) > 0) await nodes.first().click()

    const bar = page.getByTestId('guide-notification-stack-bar')
    test.skip(!(await bar.isVisible({ timeout: 25_000 }).catch(() => false)), 'No stacked guide bar for dismiss')
    await bar.click()
    await page.getByTestId('guide-notification-row').first().click()

    const strip = page.getByTestId('system-prompt-actions')
    await expect(strip).toBeVisible({ timeout: 15_000 })

    await strip.getByRole('button', { name: 'Dismiss' }).click()
    await expect(page.getByTestId('system-prompt-actions')).toHaveCount(0)
  })
})

test.describe('A3 VE AI-assisted outcomes', () => {
  test('Initiative evaluate → Dismiss clears AI proposal panel', async ({ page }) => {
    await openAppLoggedIn(page)
    await page.getByRole('navigation', { name: 'Primary' }).getByRole('button', { name: 'Vision (tables)' }).click()
    await page.getByText('Loading…').waitFor({ state: 'hidden', timeout: 60_000 }).catch(() => {})

    const noData = page.getByText('No initiatives or projects yet.')
    test.skip(await noData.isVisible().catch(() => false), 'No VE data')

    await page.locator('div.cursor-pointer').filter({ hasText: /Initiative ·/ }).first().click()
    await page.getByRole('button', { name: 'Decision / Summary' }).click()
    await page.getByTestId('initiative-run-evaluation').click()

    const proposal = page.getByRole('heading', { name: 'AI proposal' })
    await proposal.waitFor({ state: 'visible', timeout: 90_000 })
    await page.getByTestId('initiative-eval-dismiss').click()
    await expect(proposal).toHaveCount(0)
  })

  test('Focused field stub action → preview notice (partial capability)', async ({ page }) => {
    await openAppLoggedIn(page)
    await page.getByRole('navigation', { name: 'Primary' }).getByRole('button', { name: 'Vision (tables)' }).click()
    await page.getByText('Loading…').waitFor({ state: 'hidden', timeout: 60_000 }).catch(() => {})

    const noData = page.getByText('No initiatives or projects yet.')
    test.skip(await noData.isVisible().catch(() => false), 'No VE data')

    await page.locator('div.cursor-pointer').filter({ hasText: /Initiative ·/ }).first().click()
    await page.getByRole('textbox', { name: 'Brief' }).click()

    const bar = page.getByTestId('ve-context-action-bar')
    await expect(bar).toBeVisible()
    await bar.getByRole('button', { name: 'Distill' }).click()

    await expect(page.getByRole('status')).toContainText(/preview only/i, { timeout: 10_000 })
  })
})
