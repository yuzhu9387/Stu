import { useState, useRef, useEffect } from 'react'
import { api } from '../api/client'

const USER_ID = 1
interface Message { role: 'user' | 'assistant'; text: string; options?: string[] }

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [sessionId, setSessionId] = useState<number | undefined>()
  const [loading, setLoading] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages])

  const send = async (text: string) => {
    if (!text.trim()) return
    setMessages(prev => [...prev, { role: 'user', text }])
    setInput('')
    setLoading(true)
    try {
      const res = await api.chat(USER_ID, text, sessionId)
      setSessionId(res.session_id)
      setMessages(prev => [...prev, { role: 'assistant', text: res.question || res.message || (res.flow_complete ? 'Done! All info collected.' : '...'), options: res.options }])
      if (res.flow_complete) setSessionId(undefined)
    } catch { setMessages(prev => [...prev, { role: 'assistant', text: 'Error connecting.' }]) }
    finally { setLoading(false) }
  }

  return (
    <div className="flex flex-col h-[calc(100vh-3rem)]">
      <h2 className="text-2xl font-semibold text-gray-800 mb-4">Chat</h2>
      <div className="flex-1 overflow-auto space-y-3 mb-4">
        {messages.map((msg, i) => (
          <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-md px-4 py-2 rounded-2xl text-sm ${msg.role === 'user' ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-800'}`}>
              {msg.text}
              {msg.options && <div className="flex flex-wrap gap-2 mt-2">
                {msg.options.map(opt => <button key={opt} onClick={() => send(opt)} className="px-3 py-1 text-xs bg-white text-blue-600 rounded-full border border-blue-200 hover:bg-blue-50">{opt}</button>)}
              </div>}
            </div>
          </div>
        ))}
        {loading && <div className="flex justify-start"><div className="bg-gray-100 rounded-2xl px-4 py-2 text-sm text-gray-400">Thinking...</div></div>}
        <div ref={bottomRef} />
      </div>
      <div className="flex gap-2">
        <input value={input} onChange={e => setInput(e.target.value)} onKeyDown={e => e.key === 'Enter' && send(input)} placeholder="Type a message..." className="flex-1 border border-gray-300 rounded-xl px-4 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
        <button onClick={() => send(input)} disabled={loading} className="px-5 py-2 bg-blue-600 text-white rounded-xl text-sm hover:bg-blue-700 disabled:opacity-50">Send</button>
      </div>
    </div>
  )
}
