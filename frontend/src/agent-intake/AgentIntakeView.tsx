import { useEffect, useRef, useState } from 'react'
import { apiBase } from '../apiBase'

type Msg = { role: 'user' | 'muse'; text: string }

export default function AgentIntakeView() {
  const [msgs, setMsgs] = useState<Msg[]>([
    {
      role: 'muse',
      text: 'Paste one of your AI conversations here — or drop a share link — and I\u2019ll sort it into your seven strands and pull out your projects. Redacted at capture; nothing trains until you review it.',
    },
  ])
  const [input, setInput] = useState('')
  const [thinking, setThinking] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [msgs, thinking])

  async function send() {
    const text = input.trim()
    if (!text || thinking) return
    const userMsg: Msg = { role: 'user', text }
    setMsgs((m) => [...m, userMsg])
    setInput('')
    setThinking(true)
    try {
      const r = await fetch(`${apiBase()}/agents/intake/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: text,
          history: [...msgs, userMsg].slice(-10).map((m) => ({ role: m.role, content: m.text.slice(0, 2000) })),
        }),
      })
      const data = await r.json()
      setMsgs((m) => [...m, { role: 'muse', text: data.reply || 'Hmm, that didn\u2019t come through. Try again?' }])
    } catch {
      setMsgs((m) => [...m, { role: 'muse', text: 'I couldn\u2019t reach the server. Check your connection and try again.' }])
    } finally {
      setThinking(false)
    }
  }

  return (
    <div className="flex-1 flex flex-col min-h-0 max-w-2xl mx-auto w-full">
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {msgs.map((m, i) => (
          <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div
              className={`max-w-[85%] rounded-2xl px-4 py-3 text-[15px] leading-relaxed whitespace-pre-wrap ${
                m.role === 'user'
                  ? 'bg-yellow-500/90 text-stone-900'
                  : 'bg-stone-800 text-stone-200 border border-stone-700'
              }`}
            >
              {m.role === 'user' && m.text.length > 300 ? m.text.slice(0, 300) + '\u2026' : m.text}
            </div>
          </div>
        ))}
        {thinking && (
          <div className="flex justify-start">
            <div className="bg-stone-800 border border-stone-700 rounded-2xl px-4 py-3 text-stone-400 text-[15px]">
              Reading…
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>
      <div className="shrink-0 p-4 border-t border-stone-800">
        <div className="flex gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }}
            placeholder="Paste a conversation or drop a link…"
            rows={2}
            className="flex-1 min-h-[44px] px-3 py-2.5 rounded-xl bg-stone-800 text-stone-100 text-[15px] border border-stone-700 focus:border-yellow-500/60 outline-none resize-none"
          />
          <button
            onClick={send}
            disabled={thinking || !input.trim()}
            className="min-h-[44px] px-5 rounded-xl bg-yellow-500/90 text-stone-900 font-semibold text-[15px] disabled:opacity-40 self-end"
          >
            Send
          </button>
        </div>
      </div>
    </div>
  )
}
