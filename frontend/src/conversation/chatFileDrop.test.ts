import { describe, expect, it } from 'vitest'
import { appendChatDroppedFiles, CHAT_DROP_MAX_IMAGE_INLINE_BYTES, dataTransferHasFiles } from './chatFileDrop'

describe('dataTransferHasFiles', () => {
  it('is true when Files type is present', () => {
    const dt = { types: ['text/plain', 'Files'] } as unknown as DataTransfer
    expect(dataTransferHasFiles(dt)).toBe(true)
  })

  it('is false when Files type is absent', () => {
    const dt = { types: ['text/plain'] } as unknown as DataTransfer
    expect(dataTransferHasFiles(dt)).toBe(false)
  })
})

describe('appendChatDroppedFiles', () => {
  it('returns current when no files', async () => {
    expect(await appendChatDroppedFiles('hi', null)).toBe('hi')
    expect(await appendChatDroppedFiles('hi', [])).toBe('hi')
  })

  it('inlines text file contents', async () => {
    const f = new File(['hello world'], 'note.txt', { type: 'text/plain' })
    const out = await appendChatDroppedFiles('start', [f])
    expect(out.startsWith('start')).toBe(true)
    expect(out).toContain('note.txt')
    expect(out).toContain('hello world')
  })

  it('uses placeholder for oversized images', async () => {
    const big = new Uint8Array(CHAT_DROP_MAX_IMAGE_INLINE_BYTES + 1)
    const f = new File([big], 'huge.png', { type: 'image/png' })
    const out = await appendChatDroppedFiles('', [f])
    expect(out).toContain('too large')
    expect(out).not.toContain('data:image')
  })
})
