/**
 * Test-only ambient declarations: the frontend bundle has no @types/node
 * dependency (it never ships node code), but vitest tests run in node.
 * This declares exactly the functions those tests use — nothing else —
 * so node APIs stay unusable everywhere else by accident.
 *
 * Users: vision-map/cairnConversationColour.test.ts reads a stylesheet
 * off disk to pin a CSS rule; jynx-scroll/sceneHarness.test.ts reads
 * PNG assets to inline into its render pages, writes those pages, and
 * locates them via import.meta.url + SCENE_HARNESS_OUT.
 */
declare module 'node:fs' {
  export function readFileSync(path: string | URL, encoding: 'utf8'): string
  export function readFileSync(path: string): { toString(encoding: 'base64'): string }
  export function writeFileSync(path: string, data: string): void
}

declare module 'node:url' {
  export function fileURLToPath(url: string | URL): string
}

declare module 'node:path' {
  export function dirname(path: string): string
  export function join(...parts: string[]): string
}

declare const process: { env: Record<string, string | undefined> }
