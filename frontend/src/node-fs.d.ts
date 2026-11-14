/**
 * Test-only ambient declaration: the frontend bundle has no @types/node
 * dependency (it never ships node code), but vitest tests run in node
 * and one of them (vision-map/cairnConversationColour.test.ts) reads a
 * stylesheet off disk to pin a CSS rule. This declares exactly the one
 * function that test uses — nothing else — so `node:fs` stays
 * unusable everywhere else by accident.
 */
declare module 'node:fs' {
  export function readFileSync(path: string | URL, encoding: 'utf8'): string
}
