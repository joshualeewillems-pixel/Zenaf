import type { WorkspaceRunRoutingContextPayload } from '../ai-actions'
import type { CouncilStreamSsePayload } from '../council/synthesisIntegrity'

/** Minimal /run/stream reader for Perspective Workout (does not touch global council UI state). */
export async function streamWorkoutCouncilResponse(options: {
  runApiBase: string
  question: string
  contextBlock: string
  slotIds: string[]
  perspectiveDefinitions: Record<string, unknown>[]
  buildRoutingContext: () => WorkspaceRunRoutingContextPayload
  signal: AbortSignal
}): Promise<string> {
  const body = {
    mode: 'council',
    params: {
      question: options.question,
      included_agents: options.slotIds,
      perspective_definitions: options.perspectiveDefinitions,
    },
    routing_context: options.buildRoutingContext(),
    context: {
      ...(options.contextBlock.trim() ? { context_block: options.contextBlock } : {}),
    },
  }

  const res = await fetch(`${options.runApiBase}/run/stream`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal: options.signal,
  })

  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    const detail =
      typeof (err as { detail?: unknown }).detail === 'string'
        ? (err as { detail: string }).detail
        : typeof (err as { message?: unknown }).message === 'string'
          ? (err as { message: string }).message
          : res.statusText
    throw new Error(detail || `Request failed (${res.status})`)
  }

  const reader = res.body?.getReader()
  if (!reader) throw new Error('No response body stream.')

  const decoder = new TextDecoder()
  let fullText = ''
  let buffer = ''
  let streamDone = false

  while (!streamDone) {
    const { done, value } = await reader.read()
    buffer += decoder.decode(value ?? new Uint8Array(0), { stream: !done })
    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''
    for (const line of lines) {
      if (!line.startsWith('data: ')) continue
      try {
        const payload = JSON.parse(line.slice(6)) as CouncilStreamSsePayload
        if (payload.stream_open === true) continue
        if (payload.error) throw new Error(payload.error)
        if (payload.done) {
          if (payload.chunk) {
            const c = payload.chunk
            if (!fullText.trim() || c.length > fullText.length) fullText = c
          }
          streamDone = true
          break
        }
        if (payload.chunk) fullText += payload.chunk
      } catch (e) {
        if (e instanceof SyntaxError) continue
        throw e
      }
    }
    if (done) {
      if (buffer.trim().startsWith('data: ')) {
        try {
          const payload = JSON.parse(buffer.trim().slice(6)) as CouncilStreamSsePayload
          if (payload.stream_open === true) {
            /* ignore */
          } else if (payload.error) throw new Error(payload.error)
          if (payload.chunk) fullText += payload.chunk
          if (payload.done && payload.chunk) {
            const c = payload.chunk
            if (!fullText.trim() || c.length > fullText.length) fullText = c
          }
        } catch (e) {
          if (!(e instanceof SyntaxError)) throw e
        }
      }
      break
    }
  }

  return fullText.trim() || ''
}
