// @vitest-environment jsdom
/**
 * Firebrand task-context proposal cards (Capability B).
 *
 * Parser: pure unit tests (blocks, validity, stripping).
 * Component: jsdom + createRoot + act with a mocked fetch, following
 * the CouncilChat.test.ts harness. Server state drives the cards:
 * record on mount, approve/decline mutate server state, error card on
 * 400, retry on transient failure.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import * as React from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { act } from 'react-dom/test-utils'
import TaskProposalCards from './TaskProposalCards'
import {
  parseTaskProposalBlocks,
  precedingParagraph,
  stripTaskProposalBlocks,
} from './taskProposals'

;(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

describe('parseTaskProposalBlocks', () => {
  it('parses one block with one valid proposal', () => {
    const entries = parseTaskProposalBlocks(
      'Prose.\n```task-proposal\n{"proposals": [{"title": "Call", "timeframe_commitment": "tentative"}]}\n```',
      'm1',
    )
    expect(entries).toHaveLength(1)
    expect(entries[0].valid).toBe(true)
    expect(entries[0].key).toBe('m1#0:0')
    expect(entries[0].proposal?.title).toBe('Call')
    expect(entries[0].proposal?.timeframe_commitment).toBe('tentative')
  })

  it('flags malformed JSON and invalid fields, keeps indexes stable', () => {
    const entries = parseTaskProposalBlocks(
      '```task-proposal\n{nope}\n```\n```task-proposal\n{"proposals": [{"title": "  "}, {"title": "Ok", "due_date": "2026-11-06"}]}\n```',
      'm1',
    )
    expect(entries).toHaveLength(3)
    expect(entries[0].valid).toBe(false)
    expect(entries[0].proposalIndex).toBe(-1)
    expect(entries[1].valid).toBe(false)
    expect(entries[2].valid).toBe(true)
    expect(entries[2].key).toBe('m1#1:1')
  })

  it('pins the 2026-11-04 trial failure: YAML list block is invalid, never a card', () => {
    // Verbatim stored block from the staging trial: the model was never
    // told the JSON contract, so it improvised YAML with non-schema
    // fields. The parser must keep rejecting it (JSON-only by design);
    // the fix is the prompt contract, not a YAML fallback.
    const entries = parseTaskProposalBlocks(
      'Got it.\n```task-proposal\n- title: Confirm dentist slot\n  parent: Capability B trial — dentist follow-up\n  detail: Call to confirm time for Nov 8 record\n  status: tentative\n```',
      'm1',
    )
    expect(entries).toHaveLength(1)
    expect(entries[0].valid).toBe(false)
    expect(entries[0].proposalIndex).toBe(-1)
    expect(entries[0].proposal).toBeNull()
  })

  it('strips blocks from display text but keeps the prose', () => {
    const text = 'Here is the plan.\n```task-proposal\n{"proposals": []}\n```\nLet me know.'
    const stripped = stripTaskProposalBlocks(text)
    expect(stripped).not.toContain('task-proposal')
    expect(stripped).toContain('Here is the plan.')
    expect(stripped).toContain('Let me know.')
  })
})

describe('precedingParagraph', () => {
  it('returns the last paragraph before the block', () => {
    expect(
      precedingParagraph(
        'First para.\n\nSecond para.\n```task-proposal\n{"proposals": []}\n```',
        0,
      ),
    ).toBe('Second para.')
  })

  it('returns the single paragraph when there is only one', () => {
    expect(
      precedingParagraph('Prose.\n```task-proposal\n{"proposals": []}\n```', 0),
    ).toBe('Prose.')
  })

  it('returns empty when the block has no preceding prose', () => {
    expect(
      precedingParagraph('```task-proposal\n{"proposals": []}\n```', 0),
    ).toBe('')
  })

  it('picks the paragraph before the Nth block', () => {
    const text =
      'Before one.\n```task-proposal\n{"proposals": []}\n```\nMiddle para.\n```task-proposal\n{"proposals": []}\n```'
    expect(precedingParagraph(text, 1)).toBe('Middle para.')
    expect(precedingParagraph(text, 0)).toBe('Before one.')
  })

  it('truncates to 500 raw chars', () => {
    const long = 'x'.repeat(600)
    expect(precedingParagraph(`${long}\n\`\`\`task-proposal\n{"proposals": []}\n\`\`\``, 0)).toHaveLength(500)
  })

  it('returns empty for an out-of-range block index', () => {
    expect(precedingParagraph('Prose.\n```task-proposal\n{"proposals": []}\n```', 3)).toBe('')
  })
})

describe('TaskProposalCards', () => {
  let container: HTMLDivElement
  let root: Root
  let calls: Array<{ url: string; init?: RequestInit }>
  let recordBehavior: 'ok' | 'bad' | 'fail-once'
  // W1 mock controls.
  let tasksResponse: Array<{ id: string; title: string; status: string }>
  let recordExtra: Record<string, unknown>
  let approveBehavior: 'ok' | 'conflict'
  let approveProposalExtra: Record<string, unknown>

  const ok = (payload: unknown) => ({ ok: true, status: 200, json: async () => payload }) as Response
  const fail = (status: number) => ({ ok: false, status, json: async () => ({}) }) as Response

  const CONTENT =
    'Prose.\n```task-proposal\n{"proposals": [{"title": "Call the clinic", "timeframe_commitment": "tentative", "due_date": null, "notes": "Ask"}]}\n```'

  function installFetch() {
    calls = []
    let recordAttempts = 0
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      calls.push({ url, init })
      if (url.includes('/vision-execution/task-proposals?')) {
        return Promise.resolve(ok({ proposals: [] }))
      }
      if (url.includes('/vision-execution/task-proposals') && init?.method === 'POST' && !url.includes('/approve') && !url.includes('/decline')) {
        recordAttempts += 1
        if (recordBehavior === 'bad') return Promise.resolve(fail(400))
        if (recordBehavior === 'fail-once' && recordAttempts === 1) {
          return Promise.resolve(fail(500))
        }
        return Promise.resolve(
          ok({
            id: 'p1',
            conversation_id: 'talk-1',
            source_message_id: 'm1',
            block_index: 0,
            proposal_index: 0,
            seat: 'champion',
            title: 'Call the clinic',
            parent_task_id: null,
            timeframe_commitment: 'tentative',
            due_date: null,
            notes: 'Ask',
            state: 'pending',
            created_task_id: null,
            ...recordExtra,
          }),
        )
      }
      if (url.includes('/approve')) {
        if (approveBehavior === 'conflict') {
          return Promise.resolve({
            ok: false,
            status: 409,
            json: async () => ({
              detail:
                'Parent task is no longer available. Edit the proposal to choose a different parent (or no parent), or decline it.',
            }),
          } as Response)
        }
        return Promise.resolve(
          ok({
            task: { id: 't1', title: 'Call the clinic' },
            proposal: {
              id: 'p1',
              source_message_id: 'm1',
              block_index: 0,
              proposal_index: 0,
              state: 'approved',
              created_task_id: 't1',
              title: 'Call the clinic',
              ...approveProposalExtra,
            },
          }),
        )
      }
      if (url.includes('/decline')) {
        return Promise.resolve(
          ok({
            id: 'p1',
            source_message_id: 'm1',
            block_index: 0,
            proposal_index: 0,
            state: 'declined',
            created_task_id: null,
            title: 'Call the clinic',
          }),
        )
      }
      if (url.includes('/vision-execution/tasks')) {
        return Promise.resolve(ok(tasksResponse))
      }
      return Promise.resolve(ok({}))
    })
    vi.stubGlobal('fetch', fetchMock)
  }

  async function renderCards(content = CONTENT) {
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
    await act(async () => {
      root.render(
        React.createElement(TaskProposalCards, {
          base: '',
          conversationId: 'talk-1',
          messageId: 'm1',
          seat: 'champion',
          content,
        }),
      )
    })
    // Flush the mount effect's fetches + state updates.
    for (let i = 0; i < 4; i += 1) {
      await act(async () => {
        await new Promise((r) => setTimeout(r, 0))
      })
    }
  }

  function buttonNamed(name: string): HTMLButtonElement | undefined {
    return Array.from(container.querySelectorAll('button')).find(
      (b) => (b.textContent ?? '').trim() === name,
    ) as HTMLButtonElement | undefined
  }

  beforeEach(() => {
    recordBehavior = 'ok'
    tasksResponse = []
    recordExtra = {}
    approveBehavior = 'ok'
    approveProposalExtra = {}
    installFetch()
  })

  afterEach(() => {
    act(() => {
      root?.unmount()
    })
    container?.remove()
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('records on mount and renders Approve / Edit / Decline', async () => {
    await renderCards()
    expect(container.textContent).toContain('Call the clinic')
    expect(container.textContent).toContain('Tentative timeframe')
    expect(buttonNamed('Approve')).toBeDefined()
    expect(buttonNamed('Edit')).toBeDefined()
    expect(buttonNamed('Decline')).toBeDefined()
    expect(calls.some((c) => c.url.includes('/task-proposals') && c.init?.method === 'POST')).toBe(true)
    expect(container.textContent).not.toContain('task-proposal')
  })

  it('approve posts and shows Created', async () => {
    await renderCards()
    const approve = buttonNamed('Approve')
    expect(approve).toBeDefined()
    await act(async () => {
      approve?.click()
      await new Promise((r) => setTimeout(r, 0))
    })
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0))
    })
    expect(container.textContent).toContain('Created: Call the clinic')
    expect(calls.some((c) => c.url.includes('/approve'))).toBe(true)
  })

  it('decline posts and shows Declined', async () => {
    await renderCards()
    await act(async () => {
      buttonNamed('Decline')?.click()
      await new Promise((r) => setTimeout(r, 0))
    })
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0))
    })
    expect(container.textContent).toContain('Declined: Call the clinic')
  })

  it('invalid block renders the error card with no actions', async () => {
    await renderCards(
      'Prose.\n```task-proposal\n{"proposals": [{"title": "  "}]}\n```',
    )
    expect(container.textContent).toContain("Couldn't read this proposal")
    expect(buttonNamed('Approve')).toBeUndefined()
  })

  it('server 400 on record renders the error card', async () => {
    recordBehavior = 'bad'
    await renderCards()
    expect(container.textContent).toContain("Couldn't read this proposal")
  })

  it('transient record failure offers Retry, and retry succeeds', async () => {
    recordBehavior = 'fail-once'
    await renderCards()
    expect(buttonNamed('Retry')).toBeDefined()
    await act(async () => {
      buttonNamed('Retry')?.click()
      await new Promise((r) => setTimeout(r, 0))
    })
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0))
    })
    expect(buttonNamed('Approve')).toBeDefined()
  })

  it('renders nothing when there is no block', async () => {
    await renderCards('Just prose, no proposal.')
    expect(container.textContent).toBe('')
  })

  // -- W1: evidence quote, grounding flag, parent line, originals --------

  function recordPostBody(): Record<string, unknown> {
    const post = calls.find(
      (c) => c.url.includes('/task-proposals') && c.init?.method === 'POST',
    )
    expect(post).toBeDefined()
    return JSON.parse(String(post?.init?.body ?? '{}')) as Record<string, unknown>
  }

  it('record POST sends the preceding paragraph as evidence_quote', async () => {
    await renderCards()
    expect(recordPostBody().evidence_quote).toBe('Prose.')
  })

  it('renders the exact quote with the Words matched label', async () => {
    recordExtra = {
      evidence_quote: 'We should call the clinic today.',
      grounding_flag: 'words_matched',
      original_title: 'Call the clinic',
    }
    await renderCards()
    expect(container.textContent).toContain('Verbatim words from the proposing turn')
    expect(container.textContent).toContain('We should call the clinic today.')
    expect(container.textContent).toContain('Words matched')
    expect(container.textContent).not.toContain('verified')
    expect(container.textContent).not.toContain('confirmed')
  })

  it('renders the Summarized label when the title uses wording beyond the quote', async () => {
    recordExtra = {
      evidence_quote: 'Prose.',
      grounding_flag: 'summarized',
      original_title: 'Call the clinic',
    }
    await renderCards()
    expect(container.textContent).toContain('Summarized')
    expect(container.textContent).toContain('the title uses wording beyond the quote')
  })

  it('renders the parent title, and its status only when terminal', async () => {
    tasksResponse = [{ id: 'parent-1', title: 'Dentist follow-up', status: 'Todo' }]
    recordExtra = { parent_task_id: 'parent-1' }
    await renderCards()
    expect(container.textContent).toContain('Under: Dentist follow-up')
    expect(container.textContent).not.toContain('Todo')
  })

  it('renders the parent title with a terminal status', async () => {
    tasksResponse = [{ id: 'parent-1', title: 'Dentist follow-up', status: 'Done' }]
    recordExtra = { parent_task_id: 'parent-1' }
    await renderCards()
    expect(container.textContent).toContain('Under: Dentist follow-up — Done')
  })

  it('renders Parent task no longer available when the parent is gone', async () => {
    tasksResponse = []
    recordExtra = { parent_task_id: 'gone-parent' }
    await renderCards()
    expect(container.textContent).toContain('Parent task no longer available')
  })

  it('approved view shows the pre-snapshot line for legacy rows', async () => {
    approveProposalExtra = {
      original_title: null,
      evidence_quote: null,
      grounding_flag: null,
    }
    await renderCards()
    await act(async () => {
      buttonNamed('Approve')?.click()
      await new Promise((r) => setTimeout(r, 0))
    })
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0))
    })
    expect(container.textContent).toContain('Created: Call the clinic')
    expect(container.textContent).toContain('Original proposal not recorded (pre-snapshot)')
  })

  it('approved view shows the original title when it differs', async () => {
    approveProposalExtra = { original_title: 'Old title' }
    await renderCards()
    await act(async () => {
      buttonNamed('Approve')?.click()
      await new Promise((r) => setTimeout(r, 0))
    })
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0))
    })
    expect(container.textContent).toContain('Original proposal: Old title')
  })

  it('approve 409 surfaces the server guidance', async () => {
    approveBehavior = 'conflict'
    await renderCards()
    await act(async () => {
      buttonNamed('Approve')?.click()
      await new Promise((r) => setTimeout(r, 0))
    })
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0))
    })
    expect(container.textContent).toContain('Parent task is no longer available')
    expect(container.textContent).toContain('choose a different parent')
    expect(buttonNamed('Approve')).toBeDefined()
  })
})
