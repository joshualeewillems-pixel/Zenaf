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
  strand: string
  strand_name: string
  synopsis: string
  quote: string
}

export default function ReviewChat({ agentId, agentName }: Props) {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [pendingProposal, setPendingProposal] = useState<Proposal | null>(null)
  const [confirmInput, setConfirmInput] = useState('')
  const messagesEndRef = useRef<HTMLDivElement>(null)

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  // Opening: fetch Zenaf's introduction on mount
  useEffect(() => {
    const init = async () => {
      setLoading(true)
      try {
        const r = await fetch(`${apiBase()}/agents/${agentId}/review-chat`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: '', history: [] }),
        })
        const data = await r.json()
        setMessages([{ role: 'zenaf', content: data.reply }])
      } catch (e) {
        setMessages([{
          role: 'zenaf',
          content: "I'm having trouble starting up. What would you like to discuss about this conversation?",
        }])
      } finally {
        setLoading(false)
      }
    }
    init()
  }, [agentId])

  const send = async () => {
    const text = input.trim()
    if (!text || loading) return

    const history = messages.map(m => ({ role: m.role, content: m.content }))
    setMessages(prev => [...prev, { role: 'user', content: text }])
    setInput('')
    setLoading(true)

    try {
      const r = await fetch(`${apiBase()}/agents/${agentId}/review-chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, history }),
      })
      const data = await r.json()
      setMessages(prev => [...prev, { role: 'zenaf', content: data.reply }])
      if (data.pending_proposal) {
        setPendingProposal(data.pending_proposal)
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

  const sendConfirmation = async () => {
    const text = confirmInput.trim()
    if (!text || loading || !pendingProposal) return

    const history = messages.map(m => ({ role: m.role, content: m.content }))
    const proposal = pendingProposal
    setMessages(prev => [...prev, { role: 'user', content: text }])
    setConfirmInput('')
    setLoading(true)

    try {
      const r = await fetch(`${apiBase()}/agents/${agentId}/review-chat`, {
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
      // Clear the proposal — either it was filed, or the user said no/change
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

  const handleConfirmKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendConfirmation()
    }
  }

  const handleKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  return (
    <div className="flex flex-col h-[60vh] min-h-[400px]">
      <div className="flex-1 overflow-y-auto mb-4 space-y-3">
        {messages.map((m, i) => (
          <div
            key={i}
            className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            <div
              className={`max-w-[85%] rounded-2xl px-4 py-3 text-[15px] leading-snug ${
                m.role === 'user'
                  ? 'bg-stone-700 text-stone-100'
                  : 'bg-stone-800/80 border border-stone-700 text-stone-200'
              }`}
            >
              {m.role === 'zenaf' && (
                <div className="text-xs text-stone-500 mb-1 font-medium">Zenaf</div>
              )}
              <div className="whitespace-pre-wrap">{m.content}</div>
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex justify-start">
            <div className="bg-stone-800/80 border border-stone-700 rounded-2xl px-4 py-3">
              <div className="text-xs text-stone-500 mb-1 font-medium">Zenaf</div>
              <div className="text-stone-400 text-sm">thinking…</div>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>
      {pendingProposal && (
        <div className="mb-3 rounded-xl border-2 border-amber-500/60 bg-amber-950/30 p-3">
          <div className="text-xs font-semibold text-amber-400 mb-1 uppercase tracking-wide">
            Confirm filing → {pendingProposal.strand_name}
          </div>
          <div className="text-sm text-amber-100/90 mb-2 leading-snug">
            “{pendingProposal.synopsis}”
          </div>
          <div className="flex gap-2">
            <input
              type="text"
              value={confirmInput}
              onChange={(e) => setConfirmInput(e.target.value)}
              onKeyDown={handleConfirmKey}
              placeholder="Type yes to file, or tell me what to change…"
              className="flex-1 min-h-[44px] rounded-xl bg-amber-950/50 border border-amber-500/50 text-amber-50 px-4 text-[15px] placeholder:text-amber-200/40 focus:outline-none focus:border-amber-400"
              disabled={loading}
              autoFocus
            />
            <button
              onClick={sendConfirmation}
              disabled={loading || !confirmInput.trim()}
              className="min-h-[44px] px-5 rounded-xl bg-amber-600 text-amber-50 font-semibold text-[15px] disabled:opacity-40"
            >
              Reply
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
          placeholder={`Talk with Zenaf about ${agentName}…`}
          className="flex-1 min-h-[44px] rounded-xl bg-stone-800 border border-stone-700 text-stone-200 px-4 text-[15px] placeholder:text-stone-500 focus:outline-none focus:border-stone-500"
          disabled={loading}
        />
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
