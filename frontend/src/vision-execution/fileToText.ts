/**
 * Extract plain text from uploaded documents (PDF, TXT, MD, etc.) for meeting notes.
 */

// Worker for PDF.js (Vite ?url gives a string asset URL)
import pdfWorkerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'

const TEXT_TYPES = [
  'text/plain',
  'text/markdown',
  'text/csv',
  'application/json',
  'text/html',
  'application/rtf',
]

const TEXT_EXTENSIONS = ['.txt', '.md', '.csv', '.json', '.html', '.rtf', '.log']

export const ACCEPT_UPLOAD = [
  'application/pdf',
  ...TEXT_TYPES,
].join(',')

export const ACCEPT_EXTENSIONS = '.pdf,.txt,.md,.csv,.json,.html,.rtf,.log'

/** Return true if the file is likely a PDF by type or name. */
export function isPdf(file: File): boolean {
  return file.type === 'application/pdf' || /\.pdf$/i.test(file.name)
}

/** Return true if we can read the file as text (non-PDF). */
export function isTextFile(file: File): boolean {
  if (isPdf(file)) return false
  if (TEXT_TYPES.includes(file.type)) return true
  return TEXT_EXTENSIONS.some((ext) => file.name.toLowerCase().endsWith(ext))
}

/**
 * Read a text file (TXT, MD, CSV, etc.) as UTF-8 string.
 */
function readTextFile(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result ?? ''))
    reader.onerror = () => reject(reader.error ?? new Error('Failed to read file'))
    reader.readAsText(file, 'UTF-8')
  })
}

/**
 * Extract text from a PDF using pdfjs-dist. Loads PDF.js on first use.
 */
async function readPdfFile(file: File): Promise<string> {
  const buffer = await file.arrayBuffer()
  const { getDocument, GlobalWorkerOptions } = await import('pdfjs-dist')
  if (!GlobalWorkerOptions.workerSrc && typeof pdfWorkerUrl === 'string') {
    GlobalWorkerOptions.workerSrc = pdfWorkerUrl
  }
  const pdf = await getDocument(buffer).promise
  const numPages = pdf.numPages
  const parts: string[] = []
  for (let i = 1; i <= numPages; i++) {
    const page = await pdf.getPage(i)
    const content = await page.getTextContent()
    const pageText = content.items
      .map((item) => ('str' in item ? item.str : ''))
      .join(' ')
    parts.push(pageText)
  }
  return parts.join('\n\n').replace(/\s+/g, ' ').trim()
}

/**
 * Extract plain text from an uploaded file. Supports PDF and common text types.
 */
export async function fileToText(file: File): Promise<string> {
  if (isPdf(file)) return readPdfFile(file)
  if (isTextFile(file)) return readTextFile(file)
  if (file.type.startsWith('text/')) return readTextFile(file)
  if (/\.(txt|md|csv|json|log)$/i.test(file.name)) return readTextFile(file)
  throw new Error(`Unsupported file type: ${file.type || file.name}. Use PDF, TXT, MD, CSV, or JSON.`)
}
