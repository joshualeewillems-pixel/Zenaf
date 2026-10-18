import { useState, useEffect, useRef } from 'react'
import { apiBase } from '../apiBase'

type Message = {
  role: 'user' | 'zenaf'
  content: string
}

type Props = {
  agentId: string
  agentName: string
}

type Proposal = {
  type: string
  type_name: string
  title: string
  detail: string
}

export default function MiningChat({ agentId, agentName }: Props) {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [pendingProposal, setPendingProposal] = useState<Proposal | null>(null)
  const [confirmInput, setConfirmInput] = useState('')
  // Idea graduation: the user picks the level an idea proposal files as.
  // The miner may suggest; the user decides (review philosophy).
  const [fileAs, setFileAs] = useState('idea')
  const messagesEndRef = useRef<HTMLDivElement>(null)

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  // Reset the file-as picker whenever a new proposal arrives.
  useEffect(() => {
    setFileAs('idea')
  }, [pendingProposal])

  // Opening: fetch Zenaf's introduction on mount
  useEffect(() => {
    const init = async () => {
      setLoading(true)
      try {
        const r = await fetch(`${apiBase()}/agents/${agentId}/mining-chat`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: '', history: [] }),
        })
        const data = await r.json()
        setMessages([{ role: 'zenaf', content: data.reply }])
        if (data.pending_proposal) {
          setPendingProposal(data.pending_proposal)
        }
      } catch (e) {
        setMessages([{
          role: 'zenaf',
          content: "I'm having trouble starting up. What practical things did you want to pull from this conversation?",
        }])
      } finally {
        setLoading(false)
      }
    }
    init()
  }, [agentId])

  const doSend = async (text: string) => {
    const history = messages.map(m => ({ role: m.role, content: m.content }))
    setMessages(prev => [...prev, { role: 'user', content: text }])
    setLoading(true)

    try {
      const r = await fetch(`${apiBase()}/agents/${agentId}/mining-chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, history }),
      })
      const data = await r.json()
      setMessages(prev => [...prev, { role: 'zenaf', content: data.reply }])
      if (data.pending_proposal) {
        setPendingProposal(data.pending_proposal)
      }
      if (data.entity_created) {
        // Entity was filed — could show a toast here
      }
    } catch (e) {
      setMessages(prev => [...prev, {
        role: 'zenaf',
        content: "I didn't quite catch that. Could you say it differently?",
      }])
    } finally {
      setLoading(false)
    }
  }

  const send = async () => {
    const text = input.trim()
    if (!text || loading) return
    await doSend(text)
    setInput('')
  }

  const fileThis = async () => {
    if (loading || pendingProposal) return
    await doSend("add this")
  }

  const handleKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  const doConfirm = async (text: string) => {
    const history = messages.map(m => ({ role: m.role, content: m.content }))
    const proposal = pendingProposal
      ? { ...pendingProposal, target_level: pendingProposal.type === 'idea' ? fileAs : undefined }
      : null
    setMessages(prev => [...prev, { role: 'user', content: text }])
    setConfirmInput('')
    setLoading(true)

    try {
      const r = await fetch(`${apiBase()}/agents/${agentId}/mining-chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: text,
          history,
          pending_proposal: proposal,
          is_confirmation: true,
        }),
      })
      const data = await r.json()
      setMessages(prev => [...prev, { role: 'zenaf', content: data.reply }])
      setPendingProposal(null)
      if (data.pending_proposal) {
        setPendingProposal(data.pending_proposal)
      }
    } catch (e) {
      setMessages(prev => [...prev, {
        role: 'zenaf',
        content: "I didn't quite catch that. Could you say it differently?",
      }])
      setPendingProposal(null)
    } finally {
      setLoading(false)
    }
  }

  const sendConfirmation = async () => {
    const text = confirmInput.trim()
    if (!text || loading || !pendingProposal) return
    await doConfirm(text)
  }

  const confirmWithText = async (text: string) => {
    if (loading || !pendingProposal) return
    await doConfirm(text)
  }

  const handleConfirmKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendConfirmation()
    }
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        {messages.map((m, i) => (
          <div
            key={i}
            className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-[15px] leading-snug ${
              m.role === 'user'
                ? 'ml-auto bg-stone-700 text-stone-100'
                : 'mr-auto bg-stone-800/80 text-stone-200'
            }`}
          >
            {m.content}
          </div>
        ))}
        {loading && (
          <div className="mr-auto bg-stone-800/80 rounded-2xl px-4 py-2.5">
            <div className="text-stone-400 text-sm">thinking…</div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {pendingProposal && (
        <div className="mb-3 rounded-xl border-2 border-amber-500/60 bg-amber-950/30 p-3">
          <div className="text-xs font-semibold text-amber-400 mb-1 uppercase tracking-wide">
            Confirm → {pendingProposal.type_name}: {pendingProposal.title}
          </div>
          <div className="text-sm text-amber-100/90 mb-2 leading-snug">
            {pendingProposal.detail}
          </div>
          {pendingProposal.type === 'idea' && (
            <div className="mb-2">
              <label className="block text-xs font-semibold text-amber-400 mb-1 uppercase tracking-wide">
                File as
              </label>
              <select
                value={fileAs}
                onChange={(e) => setFileAs(e.target.value)}
                disabled={loading}
                className="w-full min-h-[44px] rounded-xl bg-amber-950/50 border border-amber-500/50 text-amber-50 px-4 text-[15px] focus:outline-none focus:border-amber-400"
              >
                <option value="idea">Idea — a thought, not yet work</option>
                <option value="task">Task — small, doable</option>
                <option value="project">Project — an endeavor with a goal</option>
                <option value="initiative">Initiative — a big body of work</option>
              </select>
              {fileAs !== 'idea' && (
                <p className="text-amber-200/70 text-[13px] mt-1 leading-snug">
                  It graduates only if its practical fields are filled in — otherwise I'll tell you what's missing.
                </p>
              )}
            </div>
          )}
          <div className="flex gap-2 mb-2">
            <button
              onClick={() => confirmWithText('yes')}
              disabled={loading}
              className="flex-1 min-h-[44px] rounded-xl bg-amber-500 text-amber-950 font-bold text-[15px] disabled:opacity-40 hover:bg-amber-400"
            >
              ✓ File it
            </button>
          </div>
          <div className="flex gap-2">
            <input
              type="text"
              value={confirmInput}
              onChange={(e) => setConfirmInput(e.target.value)}
              onKeyDown={handleConfirmKey}
              placeholder="Or type what to change…"
              className="flex-1 min-h-[44px] rounded-xl bg-amber-950/50 border border-amber-500/50 text-amber-50 px-4 text-[15px] placeholder:text-amber-200/40 focus:outline-none focus:border-amber-400"
              disabled={loading}
            />
            <button
              onClick={sendConfirmation}
              disabled={loading || !confirmInput.trim()}
              className="min-h-[44px] px-5 rounded-xl bg-amber-700 text-amber-50 font-semibold text-[15px] disabled:opacity-40"
            >
              Send
            </button>
          </div>
        </div>
      )}

      <div className="flex gap-2">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKey}
          placeholder={`Pull tasks, projects, assets, people…`}
          className="flex-1 min-h-[44px] rounded-xl bg-stone-800 border border-stone-700 text-stone-200 px-4 text-[15px] placeholder:text-stone-500 focus:outline-none focus:border-stone-500"
          disabled={loading}
        />
        <button
          onClick={fileThis}
          disabled={loading || !!pendingProposal}
          title="File what we've been discussing"
          className="min-h-[44px] px-4 rounded-xl bg-stone-800 border border-amber-500/40 text-amber-400 font-semibold text-[14px] disabled:opacity-40 hover:bg-stone-700 whitespace-nowrap"
        >
          File this
        </button>
        <button
          onClick={send}
          disabled={loading || !input.trim()}
          className="min-h-[44px] px-5 rounded-xl bg-stone-700 text-stone-100 font-semibold text-[15px] disabled:opacity-40"
        >
          Send
        </button>
      </div>
    </div>
  )
}
