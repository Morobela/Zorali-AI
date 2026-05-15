import React, { useEffect, useRef, useState } from 'react'
import logo from './assets/zorali-logo.png'
import { createZoraliSocket } from './api/zoraliSocket.js'
import { apiGet, apiPost, apiPut, apiUpload, apiDelete } from './api/httpClient.js'

// ─── Suggestion cards ─────────────────────────────────────────────────────────
const SUGGESTIONS = [
  ['💻', 'Write code', 'Create a React component for a dashboard'],
  ['🔎', 'Deep research', 'Research the best local AI stack for 2026'],
  ['🎨', 'Generate image', 'Generate an image prompt for Zorali AI branding'],
  ['📎', 'Analyze files', 'Explain the uploaded project files'],
  ['🧠', 'Project assistant', 'Scan this project and tell me what is broken'],
  ['🎙️', 'Voice mode', 'Start voice assistant mode'],
]

// ─── Inline markdown renderer ──────────────────────────────────────────────────
function renderMarkdown(text) {
  const lines = text.split('\n')
  const elements = []
  let i = 0

  while (i < lines.length) {
    const line = lines[i]

    // Fenced code block
    const codeMatch = line.match(/^```(\w*)$/)
    if (codeMatch) {
      const lang = codeMatch[1] || 'text'
      const codeLines = []
      i++
      while (i < lines.length && !lines[i].startsWith('```')) {
        codeLines.push(lines[i])
        i++
      }
      elements.push(<CodeBlock key={i} lang={lang} code={codeLines.join('\n')} />)
      i++
      continue
    }

    // Bullet list
    if (line.startsWith('- ') || line.startsWith('* ')) {
      const items = []
      while (i < lines.length && (lines[i].startsWith('- ') || lines[i].startsWith('* '))) {
        items.push(lines[i].slice(2))
        i++
      }
      elements.push(
        <ul key={i}>
          {items.map((it, j) => <li key={j}>{inlineFormat(it)}</li>)}
        </ul>
      )
      continue
    }

    // Blank line → paragraph break
    if (line.trim() === '') {
      i++
      continue
    }

    // Regular paragraph line
    elements.push(<p key={i}>{inlineFormat(line)}</p>)
    i++
  }

  return elements
}

function inlineFormat(text) {
  // Bold **...** or __...__
  // Inline code `...`
  const parts = []
  const regex = /(`[^`]+`|\*\*[^*]+\*\*|__[^_]+__)/g
  let last = 0
  let m
  while ((m = regex.exec(text)) !== null) {
    if (m.index > last) parts.push(text.slice(last, m.index))
    const token = m[0]
    if (token.startsWith('`')) {
      parts.push(<code key={m.index}>{token.slice(1, -1)}</code>)
    } else {
      parts.push(<strong key={m.index}>{token.slice(2, -2)}</strong>)
    }
    last = m.index + token.length
  }
  if (last < text.length) parts.push(text.slice(last))
  return parts
}

function CodeBlock({ lang, code }) {
  const [copied, setCopied] = useState(false)
  const copy = () => {
    navigator.clipboard.writeText(code).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }
  return (
    <div className="code-block">
      <div className="code-block-header">
        <span>{lang}</span>
        <button className={`copy-btn${copied ? ' copied' : ''}`} onClick={copy}>
          {copied ? '✓ Copied' : '⎘ Copy'}
        </button>
      </div>
      <pre>{code}</pre>
    </div>
  )
}

// ─── Message component ─────────────────────────────────────────────────────────
function Message({ message }) {
  const isUser = message.role === 'user'
  const content = message.content || ''
  const citations = message.citations || []

  return (
    <div className={`message ${message.role}`}>
      <div className="bubble">
        {isUser
          ? <div className="bubble-text"><p>{content}{message.streaming && <span className="stream-cursor" />}</p></div>
          : <div className="bubble-text">
              {renderMarkdown(content)}
              {message.streaming && <span className="stream-cursor" />}
            </div>
        }
        {citations.length > 0 && (
          <div className="citations">
            {citations.map((c, i) => (
              <span key={i} className="citation-chip" title={`Score: ${c.score}`}>
                📄 {c.filename}#{c.chunk_id}
              </span>
            ))}
          </div>
        )}
      </div>
      {message.meta && !isUser && (
        <div className="msg-meta">
          Trust {Math.round((message.meta.trust_score || 0.82) * 100)}% · {message.meta.reasoning_depth}
        </div>
      )}
    </div>
  )
}

// ─── Toast ─────────────────────────────────────────────────────────────────────
function Toast({ toasts }) {
  return (
    <div className="toast-container">
      {toasts.map(t => (
        <div key={t.id} className={`toast ${t.type}`}>{t.message}</div>
      ))}
    </div>
  )
}

// ─── New Project Modal ─────────────────────────────────────────────────────────
function NewProjectModal({ onConfirm, onCancel }) {
  const [name, setName] = useState('')
  return (
    <div className="modal-backdrop" onClick={onCancel}>
      <div className="modal-box" onClick={e => e.stopPropagation()}>
        <h3>New Project</h3>
        <input
          className="modal-input"
          placeholder="Project name"
          value={name}
          autoFocus
          onChange={e => setName(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && name.trim() && onConfirm(name.trim())}
        />
        <div className="modal-actions">
          <button className="modal-cancel" onClick={onCancel}>Cancel</button>
          <button className="modal-confirm" disabled={!name.trim()} onClick={() => onConfirm(name.trim())}>
            Create
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Main App ──────────────────────────────────────────────────────────────────
export default function ZoraliAI() {
  // Chat state
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [connected, setConnected] = useState(false)
  const [mode, setMode] = useState('chat')
  const [selectedModel, setSelectedModel] = useState('llama3.2:1b')
  const [localFirst, setLocalFirst] = useState(true)
  const [deepResearch, setDeepResearch] = useState(false)
  const [ollamaOk, setOllamaOk] = useState(null)
  const [providerStatus, setProviderStatus] = useState(null)
  const socketRef = useRef(null)
  const sessionId = useRef(crypto.randomUUID())
  const bottomRef = useRef(null)

  // Projects (loaded from API)
  const [projects, setProjects] = useState([])
  const [activeProjectId, setActiveProjectId] = useState('default')
  const [showNewProject, setShowNewProject] = useState(false)

  // File attachments
  const fileInputRef = useRef(null)
  const [attachedFiles, setAttachedFiles] = useState([]) // {name, id} after upload

  // Right panel state: null | 'status' | 'deepSearch' | 'artifacts' | 'memory'
  const [panel, setPanel] = useState(null)
  const [panelData, setPanelData] = useState(null)
  const [panelLoading, setPanelLoading] = useState(false)
  const [memoryQuery, setMemoryQuery] = useState('')

  // Connectors
  const [connectors, setConnectors] = useState({ Zorali: true, Web: true, Gemini: false, GPT: false, Images: false })

  // Toasts
  const [toasts, setToasts] = useState([])
  const toastId = useRef(0)

  function showToast(message, type = 'info', duration = 3500) {
    const id = ++toastId.current
    setToasts(prev => [...prev, { id, message, type }])
    setTimeout(() => setToasts(prev => prev.filter(t => t.id !== id)), duration)
  }

  // ── Load projects on mount ────────────────────────────────────────────────
  useEffect(() => {
    apiGet('/api/project')
      .then(data => {
        if (data.length > 0) {
          setProjects(data)
          setActiveProjectId(data[0].id)
        } else {
          // Create default project if none exist
          return apiPost('/api/project', { name: 'Default', description: 'Default project' })
            .then(p => { setProjects([p]); setActiveProjectId(p.id) })
        }
      })
      .catch(() => {
        // Backend not running yet — keep local default
        setProjects([{ id: 'default', name: 'Zorali AI' }])
      })
  }, [])

  useEffect(() => {
    apiGet('/api/ollama/health').then(r => setOllamaOk(!!r.ok)).catch(() => setOllamaOk(false))
    apiGet('/api/providers/status').then(setProviderStatus).catch(() => {})
  }, [])

  // ── WebSocket ──────────────────────────────────────────────────────────────
  useEffect(() => {
    const socket = createZoraliSocket(sessionId.current, {
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
          setMessages(prev => prev.map((m, i) =>
            i === prev.length - 1
              ? { ...m, streaming: false, meta: msg, citations: msg.citations || [] }
              : m
          ))
        }
        if (msg.type === 'status') {
          setPanelData(msg.data)
          setPanel('status')
          setPanelLoading(false)
        }
        if (msg.type === 'task_result') {
          setMessages(prev => [...prev, {
            role: 'assistant',
            content: JSON.stringify(msg.data, null, 2),
            streaming: false,
            meta: { reasoning_depth: 'task' },
            citations: msg.data.citations || [],
          }])
        }
        if (msg.type === 'error') {
          setMessages(prev => [...prev, { role: 'assistant', content: `⚠️ ${msg.content}`, streaming: false }])
        }
      }
    })
    socketRef.current = socket
    return () => socket.close()
  }, [])

  // Auto-scroll
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // ── Send message ──────────────────────────────────────────────────────────
  function send(customText) {
    const text = (customText || input).trim()
    if (!text) return
    setInput('')
    setMessages(prev => [
      ...prev,
      { role: 'user', content: text },
      { role: 'assistant', content: '', streaming: true },
    ])
    socketRef.current?.send({
      mode,
      message: text,
      project_id: activeProjectId,
      model: selectedModel,
      local_first: localFirst,
      deep_research: deepResearch,
      attachments: attachedFiles,
    })
  }

  // ── Project actions ───────────────────────────────────────────────────────
  async function handleAddProject(name) {
    setShowNewProject(false)
    try {
      const project = await apiPost('/api/project', { name, description: '' })
      setProjects(prev => [...prev, project])
      setActiveProjectId(project.id)
      showToast(`Project "${name}" created!`, 'success')
    } catch (e) {
      showToast(`Failed to create project: ${e.message}`, 'error')
    }
  }

  // ── File attach ───────────────────────────────────────────────────────────
  async function handleFileSelect(e) {
    const files = Array.from(e.target.files || [])
    if (!files.length) return
    for (const file of files) {
      const fd = new FormData()
      fd.append('file', file)
      try {
        showToast(`Uploading ${file.name}…`, 'info', 10000)
        const result = await apiUpload(`/api/files/upload?project_id=${activeProjectId}`, fd)
        setAttachedFiles(prev => [...prev, { name: file.name, id: result.id }])
        showToast(`✓ ${file.name} uploaded & indexed`, 'success')
      } catch (err) {
        showToast(`Upload failed: ${err.message}`, 'error')
      }
    }
    e.target.value = ''
  }

  async function removeAttachedFile(fileId, fileName) {
    try {
      await apiDelete(`/api/files/${fileId}`)
      setAttachedFiles(prev => prev.filter(f => f.id !== fileId))
      showToast(`Removed ${fileName}`, 'info')
    } catch {
      setAttachedFiles(prev => prev.filter(f => f.id !== fileId))
    }
  }

  // ── Panel actions ─────────────────────────────────────────────────────────
  function togglePanel(name) {
    if (panel === name) { setPanel(null); return }
    setPanel(name)
    setPanelData(null)
    if (name === 'status') {
      setPanelLoading(true)
      socketRef.current?.send({ mode: 'status', project_path: '/workspace' })
    }
    if (name === 'artifacts') loadArtifacts()
    if (name === 'memory') loadMemory()
    if (name === 'deepSearch') setPanelData({ steps: ['Planning research path', 'Browsing sources', 'Cross-checking memory', 'Synthesizing answer'] })
  }

  async function loadArtifacts() {
    setPanelLoading(true)
    try {
      const data = await apiGet(`/api/artifacts?project_id=${activeProjectId}`)
      setPanelData({ type: 'artifacts', items: data, selected: null, editContent: '' })
    } catch (e) {
      showToast(`Failed to load artifacts: ${e.message}`, 'error')
    } finally {
      setPanelLoading(false)
    }
  }

  async function loadMemory() {
    setPanelLoading(true)
    try {
      const data = await apiGet(`/api/project/${activeProjectId}/chats`)
      setPanelData({ type: 'memory', items: data })
    } catch (e) {
      showToast(`Failed to load memory: ${e.message}`, 'error')
    } finally {
      setPanelLoading(false)
    }
  }

  async function saveMemory() {
    if (!input.trim()) return showToast('Type memory text in composer first.', 'info')
    try {
      await apiPost('/api/memory', { project_id: activeProjectId, user_id: 'local', text: input.trim() })
      showToast('Memory saved', 'success')
      if (panel === 'memory') loadMemory()
    } catch (e) { showToast(`Memory save failed: ${e.message}`, 'error') }
  }

  async function searchMemory() {
    try {
      const data = await apiGet(`/api/memory/semantic-search?project_id=${activeProjectId}&user_id=local&q=${encodeURIComponent(memoryQuery || 'project')}`)
      setPanelData({ type: 'memory_search', ...data })
    } catch (e) { showToast(`Memory search failed: ${e.message}`, 'error') }
  }

  async function deleteMemory(id) {
    await apiDelete(`/api/memory/${id}?user_id=local`)
    loadMemory()
  }

  async function saveArtifact(artifactId, content) {
    try {
      await apiPut(`/api/artifacts/${artifactId}`, { content })
      showToast('Artifact saved!', 'success')
      loadArtifacts()
    } catch (e) {
      showToast(`Save failed: ${e.message}`, 'error')
    }
  }

  async function createArtifact() {
    const name = prompt('Artifact name:')
    if (!name) return
    try {
      await apiPost('/api/artifacts', { project_id: activeProjectId, name, content: '' })
      showToast(`Artifact "${name}" created`, 'success')
      loadArtifacts()
    } catch (e) {
      showToast(`Failed: ${e.message}`, 'error')
    }
  }

  // ─── Render ──────────────────────────────────────────────────────────────
  return (
    <div className="zorali-shell">
      {/* ── Sidebar ── */}
      <aside className="sidebar">
        <div className="brand">
          <img src={logo} alt="Zorali AI" />
          <div className="brand-text">
            <strong>Zorali AI</strong>
            <span>Local J.A.R.V.I.S.</span>
          </div>
        </div>

        <button className="new-chat" onClick={() => setMessages([])}>+ New chat</button>
        <input className="sidebar-search" placeholder="Search chats…" />

        <section>
          <div className="section-title">
            Projects
            <button title="New project" onClick={() => setShowNewProject(true)}>+</button>
          </div>
          {projects.map(p => (
            <div
              key={p.id}
              className={`project-item${p.id === activeProjectId ? ' active' : ''}`}
              onClick={() => setActiveProjectId(p.id)}
            >
              ▣ {p.name}
            </div>
          ))}
        </section>

        <section>
          <div className="section-title">Recent</div>
          <div className="recent-item active">Zorali AI build</div>
          <div className="recent-item">Website deployment</div>
          <div className="recent-item">Research notes</div>
        </section>

        <div className="sidebar-bottom">
          <span className={`conn-dot ${connected ? 'online' : 'offline'}`}>●</span>
          <span>{connected ? 'Connected' : 'Disconnected'}</span>
        </div>
      </aside>

      {/* ── Main ── */}
      <main className="main">
        <header className="topbar">
          <div className="topbar-left">
            <h1>Zorali AI</h1>
            <p>Chat · Code · Research · Project Status · Safe Tools</p>
          </div>
          <div className="pills">
            <button
              className={`pill-btn${panel === 'status' ? ' active' : ''}`}
              onClick={() => togglePanel('status')}
            >Reality Scan</button>
            <button
              className={`pill-btn${panel === 'artifacts' ? ' active' : ''}`}
              onClick={() => togglePanel('artifacts')}
            >Artifacts</button>
            <button
              className={`pill-btn${panel === 'memory' ? ' active' : ''}`}
              onClick={() => togglePanel('memory')}
            >Memory</button>
            <button
              className={`pill-btn${panel === 'deepSearch' ? ' active' : ''}`}
              onClick={() => togglePanel('deepSearch')}
            >Deep Search</button>
          </div>
        </header>

        <div className="connector-bar">
          <select value={selectedModel} onChange={e => setSelectedModel(e.target.value)} className="conn-btn connected">
            <option value="llama3.2:1b">llama3.2:1b (Local)</option>
            <option value="gpt-4o-mini">gpt-4o-mini (Cloud)</option>
          </select>
          <button className={`conn-btn${localFirst ? ' connected' : ''}`} onClick={() => setLocalFirst(v => !v)}>
            {localFirst ? '●' : '○'} Local-first
          </button>
          <button className={`conn-btn${deepResearch ? ' connected' : ''}`} onClick={() => setDeepResearch(v => !v)}>
            {deepResearch ? '●' : '○'} Deep Research
          </button>
          <button className={`conn-btn${mode === 'code' ? ' connected' : ''}`} onClick={() => setMode(mode === 'code' ? 'chat' : 'code')}>
            {mode === 'code' ? '●' : '○'} Code Mode
          </button>
          <button className={`conn-btn${ollamaOk ? ' connected' : ''}`} onClick={() => togglePanel('status')}>
            {ollamaOk ? '●' : '○'} Ollama {ollamaOk ? 'Ready' : 'Offline'}
          </button>
          {providerStatus && (
            <span className="conn-btn connected">
              Active:{' '}{providerStatus.last_used_provider || 'n/a'} · Fallback:{' '}{providerStatus.fallback_used ? 'yes' : 'no'}
            </span>
          )}
          <button className="conn-btn connected" onClick={() => togglePanel('memory')}>
            ● Memory ({messages.length})
          </button>
          {Object.entries(connectors).map(([name, active]) => (
            <button
              key={name}
              className={`conn-btn${active ? ' connected' : ''}`}
              onClick={() => setConnectors(prev => ({ ...prev, [name]: !active }))}
            >
              {active ? '●' : '○'} {name}
            </button>
          ))}
        </div>

        <section className="chat-area">
          {messages.length === 0 && (
            <div className="welcome">
              <img src={logo} alt="Zorali AI" />
              <h2>How can Zorali help?</h2>
              <p>Choose a starter or ask anything about your project.</p>
              <div className="cards">
                {SUGGESTIONS.map(([icon, title, prompt]) => (
                  <button key={title} className="card-btn" onClick={() => send(prompt)}>
                    <span className="card-icon">{icon}</span>
                    <strong>{title}</strong>
                    <small>{prompt}</small>
                  </button>
                ))}
              </div>
            </div>
          )}
          {messages.map((m, i) => <Message key={i} message={m} />)}
          <div ref={bottomRef} />
        </section>

        <footer className="composer">
          <div className="composer-toolbar">
            {['chat', 'task'].map(x => (
              <button
                key={x}
                className={`toolbar-btn${mode === x ? ' mode-active' : ''}`}
                onClick={() => setMode(x)}
              >{x}</button>
            ))}
            <button className="toolbar-btn" onClick={() => fileInputRef.current?.click()}>📎 Attach</button>
            <button className="toolbar-btn" onClick={() => showToast('Voice mode coming soon!', 'info')}>🎙 Voice</button>
            <button className="toolbar-btn" onClick={() => showToast('Image generation coming soon!', 'info')}>🎨 Image</button>
            <button className="toolbar-btn" onClick={() => setMode('task')}>💻 Code</button>
            <input
              ref={fileInputRef}
              type="file"
              style={{ display: 'none' }}
              multiple
              accept=".txt,.md,.json,.csv,.py,.js,.ts,.jsx,.tsx,.html,.css,.toml,.yaml,.yml,.xml,.sh,.pdf"
              onChange={handleFileSelect}
            />
          </div>

          {attachedFiles.length > 0 && (
            <div className="file-pills">
              {attachedFiles.map(f => (
                <span key={f.id} className="file-pill">
                  📄 {f.name}
                  <button onClick={() => removeAttachedFile(f.id, f.name)} title="Remove">✕</button>
                </span>
              ))}
            </div>
          )}

          <div className="composer-input-row">
            <textarea
              className="composer-textarea"
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() }
              }}
              placeholder="Message Zorali AI…"
            />
            <button className="send-btn" onClick={() => send()} disabled={!input.trim()}>Send</button>
          </div>
        </footer>
      </main>

      {/* ── Right Panel ── */}
      <aside className={`right-panel${panel ? ' open' : ''}`}>
        {panel && (
          <>
            <div className="panel-header">
              <h3>
                {panel === 'status' && '🛰 Reality Status'}
                {panel === 'artifacts' && '📦 Artifacts'}
                {panel === 'memory' && '🧠 Memory'}
                {panel === 'deepSearch' && '🔎 Deep Search'}
              </h3>
              <button className="panel-close" onClick={() => setPanel(null)}>✕</button>
            </div>

            <div className="panel-body">
              {panelLoading && <p style={{ color: 'var(--zorali-muted)', fontSize: 13 }}>Loading…</p>}

              {/* Status panel */}
              {panel === 'status' && panelData && (
                <pre className="status-pre">{JSON.stringify(panelData, null, 2)}</pre>
              )}

              {/* Deep Search panel */}
              {panel === 'deepSearch' && panelData?.steps && panelData.steps.map((s, i) => (
                <div key={i} className="step-item">{i + 1}. {s}</div>
              ))}

              {/* Memory panel */}
              {panel === 'memory' && panelData?.items && (
                panelData.items.length === 0
                  ? <p style={{ color: 'var(--zorali-muted)', fontSize: 13 }}>No chat history yet.</p>
                  : panelData.items.map((m, i) => (
                    <div key={i} className="memory-item">
                      <div className="memory-role">{m.role}</div>
                      <div className="memory-content">{(m.content || '').slice(0, 120)}{m.content?.length > 120 ? '…' : ''}</div>
                    </div>
                  ))
              )}
              {panel === 'memory' && (
                <div style={{marginTop: 12}}>
                  <button className="toolbar-btn" onClick={saveMemory}>Save composer as memory</button>
                  <div style={{display:'flex', gap:8, marginTop:8}}>
                    <input value={memoryQuery} onChange={e=>setMemoryQuery(e.target.value)} placeholder="Search memory..." />
                    <button className="toolbar-btn" onClick={searchMemory}>Search</button>
                  </div>
                  {panelData?.type === 'memory_search' && (
                    <div>
                      <small>{panelData.note}</small>
                      {(panelData.results || []).map((m) => (
                        <div key={m.id} className="memory-item">
                          <div className="memory-content">{m.text}</div>
                          <button className="toolbar-btn" onClick={() => deleteMemory(m.id)}>Delete</button>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Artifacts panel */}
              {panel === 'artifacts' && panelData?.type === 'artifacts' && (
                <>
                  <button className="artifact-new-btn" onClick={createArtifact}>+ New Artifact</button>
                  <div className="artifact-list">
                    {panelData.items.length === 0 && (
                      <p style={{ color: 'var(--zorali-muted)', fontSize: 13 }}>No artifacts yet. Create one!</p>
                    )}
                    {panelData.items.map(a => (
                      <div key={a.id}>
                        <div
                          className={`artifact-card${panelData.selected === a.id ? ' selected' : ''}`}
                          onClick={() => {
                            const latest = a.versions?.[a.versions.length - 1]?.content || ''
                            setPanelData(prev => ({
                              ...prev,
                              selected: prev.selected === a.id ? null : a.id,
                              editContent: latest,
                            }))
                          }}
                        >
                          <div className="artifact-name">📄 {a.name}</div>
                          <div className="artifact-meta">v{a.versions?.length || 1} · {new Date(a.created_at).toLocaleDateString()}</div>
                        </div>
                        {panelData.selected === a.id && (
                          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 6 }}>
                            <textarea
                              className="artifact-editor"
                              value={panelData.editContent}
                              onChange={e => setPanelData(prev => ({ ...prev, editContent: e.target.value }))}
                            />
                            <button className="artifact-save-btn" onClick={() => saveArtifact(a.id, panelData.editContent)}>
                              Save
                            </button>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>
          </>
        )}
      </aside>

      {/* ── Modals & Toasts ── */}
      {showNewProject && (
        <NewProjectModal
          onConfirm={handleAddProject}
          onCancel={() => setShowNewProject(false)}
        />
      )}
      <Toast toasts={toasts} />
    </div>
  )
}
