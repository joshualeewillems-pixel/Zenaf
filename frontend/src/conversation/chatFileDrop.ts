/**
 * Shared logic for dropping files into chat-style composers (council, workout, etc.).
 * Text-like files are inlined; images become markdown data-URLs when under a size cap.
 */

const TEXT_EXTENSIONS = new Set([
  'txt',
  'md',
  'markdown',
  'csv',
  'json',
  'jsonl',
  'xml',
  'html',
  'htm',
  'yaml',
  'yml',
  'log',
  'ts',
  'tsx',
  'js',
  'jsx',
  'py',
  'rs',
  'go',
  'java',
  'c',
  'h',
  'cpp',
  'css',
  'scss',
  'sql',
  'sh',
  'toml',
  'ini',
  'cfg',
])

/** Inline images up to this size (bytes); larger files get a placeholder line. */
export const CHAT_DROP_MAX_IMAGE_INLINE_BYTES = 512 * 1024

function extensionOf(name: string): string {
  const i = name.lastIndexOf('.')
  return i >= 0 ? name.slice(i + 1).toLowerCase() : ''
}

function isLikelyTextFile(file: File): boolean {
  if (file.type.startsWith('text/')) return true
  if (file.type === 'application/json' || file.type === 'application/xml') return true
  return TEXT_EXTENSIONS.has(extensionOf(file.name))
}

function readAsDataURL(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader()
    r.onload = () => resolve(String(r.result ?? ''))
    r.onerror = () => reject(r.error ?? new Error('read failed'))
    r.readAsDataURL(file)
  })
}

function escapeAlt(text: string): string {
  return text.replace(/]/g, '')
}

export function dataTransferHasFiles(dt: DataTransfer): boolean {
  return [...dt.types].includes('Files')
}

/**
 * Append representations of dropped files to an existing message string.
 */
export async function appendChatDroppedFiles(
  current: string,
  files: FileList | File[] | null | undefined,
): Promise<string> {
  if (!files || (Array.isArray(files) ? files.length === 0 : files.length === 0)) {
    return current
  }
  const list = Array.from(files)
  const chunks: string[] = []
  for (const file of list) {
    if (isLikelyTextFile(file)) {
      try {
        const t = await file.text()
        chunks.push(`\n\n---\n📄 ${file.name}\n---\n${t}`)
      } catch {
        chunks.push(`\n\n[Could not read text file: ${file.name}]`)
      }
    } else if (file.type.startsWith('image/')) {
      if (file.size > CHAT_DROP_MAX_IMAGE_INLINE_BYTES) {
        chunks.push(
          `\n\n[Image “${file.name}” is too large for inline (${Math.round(file.size / 1024)} KB); max ~${Math.round(CHAT_DROP_MAX_IMAGE_INLINE_BYTES / 1024)} KB]`,
        )
      } else {
        try {
          const dataUrl = await readAsDataURL(file)
          chunks.push(`\n\n![${escapeAlt(file.name)}](${dataUrl})`)
        } catch {
          chunks.push(`\n\n[Could not read image: ${file.name}]`)
        }
      }
    } else {
      chunks.push(
        `\n\n[File: ${file.name}${file.type ? ` (${file.type})` : ''} — binary or unsupported format; export as text or describe contents.]`,
      )
    }
  }
  return current + chunks.join('')
}
