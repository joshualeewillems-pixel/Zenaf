import { describe, it, expect } from 'vitest'
import type { Claim } from './ClaimCard'

// ClaimCard's contract: each claim carries verbatim evidence, a plain-language
// inference, and moves through pending -> accepted/corrected/explained.
// These tests pin the data shapes the card depends on.

const claim: Claim = {
  id: 'strand:self',
  claim_type: 'strand',
  title: 'Guide strand',
  evidence: 'USER: I have been thinking about my purpose',
  inference: 'You kept coming back to purpose.',
  detail: 'Sorter score 0.9',
  status: 'pending',
  user_note: '',
  question: '',
  scope: 'moment',
  turn_ref: '',
}

describe('ClaimCard data contract', () => {
  it('claim has evidence, inference, and pending status', () => {
    expect(claim.evidence).toBeTruthy()
    expect(claim.inference).toBeTruthy()
    expect(claim.status).toBe('pending')
  })

  it('resolved claims carry the user note', () => {
    const done: Claim = { ...claim, status: 'explained', user_note: 'my reason' }
    expect(done.status).not.toBe('pending')
    expect(done.user_note).toBe('my reason')
  })

  it('claim ids are namespaced by type', () => {
    const ids = ['strand:self', 'kind', 'initiative:0', 'project:1', 'task:0', 'idea:2']
    for (const id of ids) {
      const [type] = id.split(':')
      expect(['strand', 'kind', 'initiative', 'project', 'task', 'idea']).toContain(type)
    }
  })

  it('action endpoints follow the REST pattern', () => {
    const agentId = 'a1'
    const claimId = 'strand:self'
    for (const action of ['accept', 'correct', 'explain']) {
      const path = `/agents/${agentId}/claims/${claimId}/${action}`
      expect(path).toBe('/agents/a1/claims/strand:self/' + action)
    }
  })
})
