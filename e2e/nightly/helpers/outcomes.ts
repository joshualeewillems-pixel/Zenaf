import type { Page, TestInfo } from '@playwright/test'

/**
 * Nightly / Playwright classification for fringe probes (see flows-b-boundaries.spec.ts).
 * Surfaces in HTML report as annotations + small text attachments (not a hard failure).
 */
export type ZenafClassification = 'PASS' | 'BOUNDARY'

export async function classify(
  info: TestInfo,
  kind: ZenafClassification,
  detail: string,
  options?: { screenshot?: Page },
): Promise<void> {
  const line = `[ZENAF_E2E] ${kind}: ${detail}`
  info.annotations.push({ type: 'zenaf-classification', description: line })
  await info.attach('zenaf-classification.txt', {
    body: `${line}\n`,
    contentType: 'text/plain',
  })
  if (options?.screenshot) {
    const buf = await options.screenshot.screenshot({ fullPage: false }).catch(() => null)
    if (buf) {
      await info.attach('zenaf-boundary-screenshot.png', {
        body: buf,
        contentType: 'image/png',
      })
    }
  }
}

/** Collect uncaught page errors during a block (use for stability probes). */
export function createPageErrorSink(page: Page): { messages: string[]; handler: (e: Error) => void } {
  const messages: string[] = []
  const handler = (err: Error) => {
    messages.push(err.message || String(err))
  }
  page.on('pageerror', handler)
  return { messages, handler }
}

export function detachPageErrorSink(page: Page, handler: (e: Error) => void): void {
  page.off('pageerror', handler)
}
