import { useCallback, useEffect, useState } from 'react'
import { apiBase } from '../apiBase'

/**
 * The per-seat QC surface — "what's being fashioned" about you.
 *
 * Reads GET /you-profile/{archetypeId}: the composed view over the ground
 * truths (per-seat depth, the canonical approved-signal store, the current
 * persona version, snapshot metadata) plus the durable You record.
 *
 * Rules this panel lives by:
 *  - Honest empty states. No training yet reads as no training yet — never
 *    placeholder data.
 *  - The You identity card (name/face presentation) stays unrevealed until
 *    keystone 4 ("The echo") is complete. The QC data is visible from day
 *    one, because checking what's being fashioned is the day-to-day point
 *    of the switch — but the echo's NAME cannot be set before then: you
 *    have to get to know it before you can name it, and the naming happens
 *    in the recognition conversation itself.
 *  - Signal anchors are shown read-only, exactly as recorded (they were
 *    redacted at capture).
 */

type KeystoneStep = { index: number; title: string; status: string; done: boolean }

type FashionedSignal = {
  signal_id: string
  summary: string
  anchor: string
  layer: string
  zone: string
  valence: string
  kind: string
  parallels: number
  is_divergence: boolean
}

type SnapshotRef = {
  snapshot_id: string
  version: number | null
  trigger: string | null
  era_name: string | null
  label: string | null
  created_at: string | null
}

type YouProfile = {
  archetype_id: string
  zenaf: { character: string; seat_name: string; demeanor: string }
  you: {
    revealed: boolean
    state: string
    personal_name: string | null
    avatar_ref: string | null
    pinned_snapshot: SnapshotRef | null
  }
  recognition: {
    status: string
    seeded: boolean
    completed: number
    total: number
    rentable: boolean
    keystones: KeystoneStep[]
  }
  fashioning: {
    depth_points: number
    milestones: {
      avatar_threshold: number
      rename_threshold: number
      avatar_unlocked: boolean
      rename_unlocked: boolean
    }
    approved_signals: FashionedSignal[]
    signal_total: number
    persona_version: number | null
    persona_version_count: number
    snapshots: SnapshotRef[]
  }
}

export function YouEchoPanel({ archetypeId, character }: { archetypeId: string; character: string }) {
  const [profile, setProfile] = useState<YouProfile | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [nameDraft, setNameDraft] = useState('')
  const [saving, setSaving] = useState(false)
  const [saveNote, setSaveNote] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const res = await fetch(`${apiBase()}/you-profile/${encodeURIComponent(archetypeId)}`, {
        credentials: 'include',
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = (await res.json()) as YouProfile
      setProfile(data)
      setNameDraft(data.you.personal_name ?? '')
      setError(null)
    } catch {
      setError('Could not load what’s being fashioned just now.')
    }
  }, [archetypeId])

  useEffect(() => {
    void load()
  }, [load])

  const saveName = async () => {
    setSaving(true)
    setSaveNote(null)
    try {
      const res = await fetch(`${apiBase()}/you-profile/${encodeURIComponent(archetypeId)}`, {
        method: 'PUT',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ personal_name: nameDraft.trim() || null }),
      })
      if (!res.ok) {
        const j = await res.json().catch(() => null)
        setSaveNote((j && j.detail) || 'Could not save the name.')
        return
      }
      setSaveNote('Saved.')
      void load()
    } catch {
      setSaveNote('Could not save the name.')
    } finally {
      setSaving(false)
    }
  }

  if (error) return <p className="lsub">{error}</p>
  if (!profile) return <p className="lsub">Looking at what’s being fashioned…</p>

  const { you, recognition, fashioning } = profile
  const divergences = fashioning.approved_signals.filter((s) => s.is_divergence)
  const parallels = fashioning.approved_signals.filter((s) => !s.is_divergence)

  return (
    <div>
      <div className="lsect">Your echo — what’s being fashioned</div>

      {you.revealed ? (
        <div>
          <p className="lnote">
            You’ve met your echo of the {character} — its card is revealed. What it goes by, between you:
          </p>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <input
              value={nameDraft}
              onChange={(e) => setNameDraft(e.target.value)}
              placeholder="Its name, as you gave it"
              aria-label="Your echo's personal name"
              style={{
                minHeight: 44, padding: '8px 12px', borderRadius: 10, flex: '1 1 160px',
                background: 'rgba(245,240,232,.06)', border: '1px solid rgba(201,168,106,.35)',
                color: '#f5f0e8', fontFamily: 'inherit', fontSize: 14,
              }}
            />
            <button type="button" className="lcta" onClick={saveName} disabled={saving}>
              {saving ? 'Saving…' : 'Save name'}
            </button>
          </div>
          {saveNote ? <p className="lnote">{saveNote}</p> : null}
          <p className="lnote">
            This seat’s echo is rentable-ready by your own standard — the meeting happened,
            and the record above is what a renter would be trusting.
          </p>
        </div>
      ) : (
        <div>
          <p className="lsub">
            Your echo of the {character} is being fashioned, but its card stays unrevealed
            until the recognition conversation (keystone 4, “The echo”) — the name, face,
            and full presentation arrive then. The switch above and everything below stay
            open in the meantime: this is yours to inspect from day one.
          </p>
          <p className="lnote">
            It doesn’t have a name yet — you have to get to know it before you can
            name it. The name comes from the recognition conversation, when the two
            of you land on one together.
          </p>
        </div>
      )}

      {recognition.seeded ? (
        <p className="lnote">
          Keystones: {recognition.completed} of {recognition.total} complete
          {recognition.keystones.length > 0
            ? ` — ${recognition.keystones.map((k) => `${k.done ? '✓' : '·'} ${k.title}`).join('  ')}`
            : ''}
        </p>
      ) : null}

      <div className="lstat">
        <span className="lname">Familiarity</span>
        <span className="lpct">{fashioning.depth_points} pts</span>
        <span className="lnote">
          {fashioning.depth_points <= 0
            ? ' — nothing approved has shaped this seat yet'
            : fashioning.milestones.rename_unlocked
              ? ' — deep enough to rename the seat'
              : fashioning.milestones.avatar_unlocked
                ? ' — deep enough to set the seat’s face'
                : ' — early shaping'}
        </span>
      </div>
      <div className="lstat">
        <span className="lname">Persona</span>
        <span className="lpct">
          {fashioning.persona_version != null ? `v${fashioning.persona_version}` : '—'}
        </span>
        <span className="lnote">
          {fashioning.persona_version != null
            ? ` — current published version (${fashioning.persona_version_count} total)`
            : ' — no published persona yet'}
        </span>
      </div>
      {fashioning.snapshots.length > 0 ? (
        <p className="lnote">
          Snapshots on record: {fashioning.snapshots.map((s) => s.label ?? s.snapshot_id).join(', ')}
          {you.pinned_snapshot ? ` · pinned for this echo: ${you.pinned_snapshot.label ?? you.pinned_snapshot.snapshot_id}` : ''}
        </p>
      ) : null}

      <div className="lsect">Approved training shaping this seat</div>
      {fashioning.approved_signals.length === 0 ? (
        <p className="lsub">
          Nothing yet — when you approve training that touches this seat, it shows up here
          with the exact words it rests on.
        </p>
      ) : (
        <div>
          {parallels.map((s) => (
            <div key={s.signal_id} style={{ margin: '10px 0' }}>
              <div style={{ fontSize: 13 }}>{s.summary}</div>
              {s.anchor && s.anchor !== s.summary ? (
                <div className="lnote" style={{ fontStyle: 'italic' }}>“{s.anchor}”</div>
              ) : null}
              <div className="lnote">
                {s.layer} · {s.zone} · {s.valence}
                {s.parallels > 0 ? ` · corroborated by ${s.parallels} parallel${s.parallels === 1 ? '' : 's'}` : ''}
              </div>
            </div>
          ))}
          {divergences.length > 0 ? (
            <div>
              <div className="lsect">Where you pushed back</div>
              {divergences.map((s) => (
                <div key={s.signal_id} style={{ margin: '10px 0' }}>
                  <div style={{ fontSize: 13 }}>{s.summary}</div>
                  {s.anchor && s.anchor !== s.summary ? (
                    <div className="lnote" style={{ fontStyle: 'italic' }}>“{s.anchor}”</div>
                  ) : null}
                  <div className="lnote">
                    {s.layer} · {s.zone} · {s.valence} — recorded as a divergence, not smoothed over
                  </div>
                </div>
              ))}
            </div>
          ) : null}
        </div>
      )}
    </div>
  )
}
