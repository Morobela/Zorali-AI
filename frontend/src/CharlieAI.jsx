import React, { useEffect, useRef, useState } from 'react'
import logo from './assets/charlie-logo.png'
import { createCharlieSocket } from './api/charlieSocket.js'

const suggestions = [
  ['💻', 'Write code', 'Create a React component for a dashboard'],
  ['🔎', 'Deep research', 'Research the best local AI stack for 2026'],
  ['🎨', 'Generate image', 'Generate an image prompt for Charlie AI branding'],
  ['📎', 'Analyze files', 'Explain the uploaded project files'],
  ['🧠', 'Project assistant', 'Scan this project and tell me what is broken'],
  ['🎙️', 'Voice mode', 'Start voice assistant mode'],
]

export default function CharlieAI() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [connected, setConnected] = useState(false)
  const [deepSearch, setDeepSearch] = useState(false)
  const [mode, setMode] = useState('chat')
  const [status, setStatus] = useState(null)
  const [projects, setProjects] = useState([{ id: 'default', name: 'Charlie AI', active: true }])
  const [connectors, setConnectors] = useState({ Charlie: true, Web: true, Gemini: false, GPT: false, Images: false })
  const socketRef = useRef(null)
  const sessionId = useRef(crypto.randomUUID())

  useEffect(() => {
    const socket = createCharlieSocket(sessionId.current, {
      onOpen: () => setConnected(true),
      onClose: () => setConnected(false),
      onMessage: (msg) => {
        if (msg.type === 'token') {
          setMessages(prev => {
            const copy = [...prev]
            const last = copy[copy.length - 1]
            if (last?.role === 'assistant' && last.streaming) last.content += msg.content
            return copy
          })
        }
        if (msg.type === 'done') {
          setMessages(prev => prev.map((m, i) => i === prev.length - 1 ? { ...m, streaming: false, meta: msg } : m))
        }
        if (msg.type === 'status') setStatus(msg.data)
        if (msg.type === 'task_result') {
          setMessages(prev => [...prev, { role: 'assistant', content: JSON.stringify(msg.data, null, 2), streaming: false, meta: { reasoning_depth: 'task' } }])
        }
        if (msg.type === 'error') setMessages(prev => [...prev, { role: 'assistant', content: msg.content, streaming: false }])
      }
    })
    socketRef.current = socket
    return () => socket.close()
  }, [])

  function send(customText) {
    const text = (customText || input).trim()
    if (!text) return
    setInput('')
    setMessages(prev => [...prev, { role: 'user', content: text }, { role: 'assistant', content: '', streaming: true }])
    const activeProjectId = projects.find((p) => p.active)?.id || 'default'
    socketRef.current?.send({ mode, message: text, project_id: activeProjectId })
  }

  function requestStatus() {
    socketRef.current?.send({ mode: 'status', project_path: '/workspace' })
  }

  return (
    <div className="charlie-shell">
      <aside className="sidebar">
        <div className="brand">
          <img src={logo} alt="Charlie AI" />
          <div><strong>Charlie AI</strong><span>Local J.A.R.V.I.S.</span></div>
        </div>
        <button className="new-chat" onClick={() => setMessages([])}>+ New chat</button>
        <input className="search" placeholder="Search chats..." />
        <section>
          <div className="section-title">Projects <button onClick={() => setProjects([...projects.map((x)=>({ ...x, active:false })), { id: crypto.randomUUID(), name: 'New Project', active:true }])}>+</button></div>
          {projects.map((p, i) => <div key={p.id || i} className={`project ${p.active ? 'active' : ''}`}>▣ {p.name}</div>)}
        </section>
        <section>
          <div className="section-title">Recent</div>
          <div className="recent active">Charlie AI build</div>
          <div className="recent">Website deployment</div>
          <div className="recent">Research notes</div>
        </section>
        <div className="sidebar-bottom">● {connected ? 'Connected' : 'Disconnected'}</div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div>
            <h1>Charlie AI</h1>
            <p>Chat · Code · Research · Project Status · Safe Tools</p>
          </div>
          <div className="pills">
            <button onClick={requestStatus}>Reality Scan</button>
            <button>Artifacts</button>
            <button>Memory</button>
            <button className={deepSearch ? 'on' : ''} onClick={() => setDeepSearch(!deepSearch)}>Deep Search</button>
          </div>
        </header>

        <div className="connector-bar">
          {Object.entries(connectors).map(([name, active]) => (
            <button key={name} className={active ? 'connected' : ''} onClick={() => setConnectors({ ...connectors, [name]: !active })}>{active ? '●' : '○'} {name}</button>
          ))}
        </div>

        <section className="chat-area">
          {messages.length === 0 && (
            <div className="welcome">
              <img src={logo} alt="Charlie AI" />
              <h2>How can Charlie help?</h2>
              <p>Choose a starter or ask anything about your project.</p>
              <div className="cards">
                {suggestions.map(([icon, title, prompt]) => <button key={title} onClick={() => { setInput(prompt); send(prompt) }}><span>{icon}</span><strong>{title}</strong><small>{prompt}</small></button>)}
              </div>
            </div>
          )}
          {messages.map((m, i) => <Message key={i} message={m} />)}
        </section>

        <footer className="composer">
          <div className="mode-row">
            {['chat','task'].map(x => <button key={x} className={mode === x ? 'active' : ''} onClick={() => setMode(x)}>{x}</button>)}
            <button>📎 Attach</button><button>🎙 Voice</button><button>🎨 Image</button><button>💻 Code</button>
          </div>
          <textarea value={input} onChange={e => setInput(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }} placeholder="Message Charlie AI..." />
          <button className="send" onClick={() => send()}>Send</button>
        </footer>
      </main>

      <aside className={`right-panel ${deepSearch || status ? 'open' : ''}`}>
        <h3>{status ? 'Reality Status' : 'Deep Search'}</h3>
        {status ? <pre>{JSON.stringify(status, null, 2)}</pre> : <div className="steps"><p>1. Planning research path</p><p>2. Browsing sources</p><p>3. Cross-checking memory</p><p>4. Synthesizing answer</p></div>}
      </aside>
    </div>
  )
}

function Message({ message }) {
  return <div className={`message ${message.role}`}>
    <div className="bubble"><pre>{message.content}{message.streaming ? '▋' : ''}</pre></div>
    {message.meta && <div className="meta">Trust {Math.round((message.meta.trust_score || .82) * 100)}% · {message.meta.reasoning_depth}</div>}
  </div>
}
