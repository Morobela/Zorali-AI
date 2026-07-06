import React, { useCallback, useEffect, useRef, useState } from 'react'
import logo from './assets/zorali-logo.png'
import { createZoraliSocket } from './api/zoraliSocket.js'
import { apiGet, apiPost, apiPut, apiUpload, apiDelete } from './api/httpClient.js'

// ─── Suggestion cards ─────────────────────────────────────────────────────────
const SUGGESTIONS = [
  ['💻', 'Write code', 'Create a React component for a dashboard'],
  ['🔎', 'Deep research', 'Research the best local AI stack for 2026'],
  ['🎨', 'Generate image', 'Generate an image prompt for Zorali branding'],
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
function Message({ message, canRegenerate, onRegenerate, onSpeak }) {
  const isUser = message.role === 'user'
  const content = message.content || ''
  const citations = message.citations || []
  const webCitations = message.web_citations || []
  const images = message.images || []
  const [copied, setCopied] = useState(false)

  const copyMessage = () => {
    navigator.clipboard.writeText(content).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }

  return (
    <div className={`message ${message.role}`}>
      <div className="bubble">
        {images.length > 0 && (
          <div className="msg-images" style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 6 }}>
            {images.map((src, i) => (
              <img key={i} src={src} alt="attachment" style={{ maxWidth: 160, maxHeight: 120, borderRadius: 8 }} />
            ))}
          </div>
        )}
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
        {webCitations.length > 0 && (
          <div className="citations">
            {webCitations.map((c, i) => (
              <a key={i} className="citation-chip" href={c.url} target="_blank" rel="noopener noreferrer" title={c.url}>
                🌐 [{c.marker}] {(c.title || c.url).slice(0, 48)}
              </a>
            ))}
          </div>
        )}
      </div>
      {!isUser && !message.streaming && content && (
        <div className="msg-actions">
          <button className="msg-action-btn" onClick={copyMessage} title="Copy message">
            {copied ? '✓ Copied' : '⎘ Copy'}
          </button>
          {onSpeak && (
            <button className="msg-action-btn" onClick={() => onSpeak(content)} title="Read aloud">
              🔊 Speak
            </button>
          )}
          {canRegenerate && (
            <button className="msg-action-btn" onClick={onRegenerate} title="Regenerate response">
              ↻ Regenerate
            </button>
          )}
        </div>
      )}
      {message.meta && !isUser && (
        <div className="msg-meta">
          {message.meta.provider && <span>{message.meta.provider}</span>}
          {message.meta.latency_ms != null && <span> · {message.meta.latency_ms}ms</span>}
          {message.meta.citation_count > 0 && <span> · {message.meta.citation_count} source{message.meta.citation_count !== 1 ? 's' : ''}</span>}
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

// ─── Project Settings Modal (custom instructions) ──────────────────────────────
function ProjectSettingsModal({ project, onSave, onCancel }) {
  const [instructions, setInstructions] = useState(project.system_prompt || '')
  return (
    <div className="modal-backdrop" onClick={onCancel}>
      <div className="modal-box" onClick={e => e.stopPropagation()}>
        <h3>{project.name} — Custom instructions</h3>
        <p style={{ fontSize: 12, color: 'var(--zorali-muted)' }}>
          Zorali follows these instructions in every chat inside this project
          (tone, format, persona, house rules).
        </p>
        <textarea
          className="modal-input"
          style={{ minHeight: 120, resize: 'vertical' }}
          placeholder="e.g. Answer concisely. We build a FastAPI + React app. Address me as Commander."
          value={instructions}
          autoFocus
          onChange={e => setInstructions(e.target.value)}
        />
        <div className="modal-actions">
          <button className="modal-cancel" onClick={onCancel}>Cancel</button>
          <button className="modal-confirm" onClick={() => onSave(instructions)}>Save</button>
        </div>
      </div>
    </div>
  )
}

// ─── Main App ──────────────────────────────────────────────────────────────────
export default function Zorali() {
  // Chat state
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [connected, setConnected] = useState(false)
  const [mode, setMode] = useState('chat')
  const [selectedModel, setSelectedModel] = useState('llama3.2:1b')
  const [availableModels, setAvailableModels] = useState(['llama3.2:1b'])
  const [localFirst, setLocalFirst] = useState(true)
  const [deepResearch, setDeepResearch] = useState(false)
  const [ollamaOk, setOllamaOk] = useState(null)
  const [providerStatus, setProviderStatus] = useState(null)
  const socketRef = useRef(null)
  // Conversation (session) management — ChatGPT-style history in the sidebar
  const [sessionKey, setSessionKey] = useState(() => crypto.randomUUID())
  const [sessions, setSessions] = useState([])
  const bottomRef = useRef(null)
  const isStreaming = messages[messages.length - 1]?.streaming === true

  // Voice mode (JARVIS): speech-to-text input + optional spoken replies
  const [listening, setListening] = useState(false)
  const [speakReplies, setSpeakReplies] = useState(false)
  const speakRepliesRef = useRef(false)
  const recognitionRef = useRef(null)

  // Projects (loaded from API)
  const [projects, setProjects] = useState([])
  const [activeProjectId, setActiveProjectId] = useState('default')
  const [showNewProject, setShowNewProject] = useState(false)
  const [settingsProject, setSettingsProject] = useState(null)

  // File attachments
  const fileInputRef = useRef(null)
  const [attachedFiles, setAttachedFiles] = useState([]) // {name, id} after upload

  // Image attachments for vision models (sent with the next message)
  const imageInputRef = useRef(null)
  const [attachedImages, setAttachedImages] = useState([]) // {name, data: dataURL}

  // Right panel state: null | 'status' | 'deepSearch' | 'artifacts' | 'memory'
  const [panel, setPanel] = useState(null)
  const [panelData, setPanelData] = useState(null)
  const [panelLoading, setPanelLoading] = useState(false)
  const [memoryQuery, setMemoryQuery] = useState('')

  // Connectors — only show real, wired integrations. Cloud providers are not yet active.
  const [connectors, setConnectors] = useState({})

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
        setProjects([{ id: 'default', name: 'Zorali' }])
      })
  }, [])

  useEffect(() => {
    apiGet('/api/ollama/health')
      .then(r => {
        setOllamaOk(!!r.ok)
        // Populate the model picker from what is actually installed in Ollama.
        if (Array.isArray(r.models) && r.models.length > 0) {
          setAvailableModels(r.models)
          if (!r.models.includes('llama3.2:1b')) setSelectedModel(r.models[0])
        }
      })
      .catch(() => setOllamaOk(false))
    apiGet('/api/providers/status').then(setProviderStatus).catch(() => {})
  }, [])

  // ── Conversation list ─────────────────────────────────────────────────────
  const loadSessions = useCallback(() => {
    if (!activeProjectId || activeProjectId === 'default') return
    apiGet(`/api/project/${activeProjectId}/sessions`)
      .then(setSessions)
      .catch(() => setSessions([]))
  }, [activeProjectId])

  useEffect(() => { loadSessions() }, [loadSessions])

  async function openSession(sid) {
    if (sid === sessionKey) return
    try {
      const history = await apiGet(`/api/project/${activeProjectId}/chats?session_id=${encodeURIComponent(sid)}`)
      setMessages(history.map(m => ({
        role: m.role,
        content: m.content,
        citations: m.citations || [],
        streaming: false,
      })))
      setSessionKey(sid)
    } catch (e) {
      showToast(`Could not open conversation: ${e.message}`, 'error')
    }
  }

  function newChat() {
    setSessionKey(crypto.randomUUID())
    setMessages([])
  }

  // ── Voice mode (Web Speech API) ───────────────────────────────────────────
  function speak(text) {
    if (!('speechSynthesis' in window)) return
    // Strip code fences and markdown decorations before speaking.
    const spoken = text
      .replace(/```[\s\S]*?```/g, ' Code block omitted. ')
      .replace(/[`*_#>]/g, '')
      .slice(0, 1200)
    window.speechSynthesis.cancel()
    window.speechSynthesis.speak(new SpeechSynthesisUtterance(spoken))
  }

  function toggleVoiceInput() {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition
    if (!SR) {
      showToast('Voice input is not supported in this browser (try Chrome/Edge).', 'error')
      return
    }
    if (listening) {
      recognitionRef.current?.stop()
      return
    }
    const rec = new SR()
    rec.interimResults = true
    rec.continuous = false
    let finalTranscript = ''
    rec.onresult = (event) => {
      let interim = ''
      for (const res of event.results) {
        if (res.isFinal) finalTranscript += res[0].transcript
        else interim += res[0].transcript
      }
      setInput(finalTranscript + interim)
    }
    rec.onend = () => {
      setListening(false)
      recognitionRef.current = null
      const text = finalTranscript.trim()
      if (text) send(text)
    }
    rec.onerror = (event) => {
      setListening(false)
      recognitionRef.current = null
      if (event.error !== 'aborted') showToast(`Voice input error: ${event.error}`, 'error')
    }
    recognitionRef.current = rec
    setListening(true)
    window.speechSynthesis?.cancel()
    rec.start()
  }

  function toggleSpeakReplies() {
    setSpeakReplies(v => {
      speakRepliesRef.current = !v
      if (v) window.speechSynthesis?.cancel()
      return !v
    })
  }

  // ── WebSocket (one connection per conversation) ───────────────────────────
  useEffect(() => {
    const socket = createZoraliSocket(sessionKey, {
      onOpen: () => setConnected(true),
      onClose: (event) => {
        setConnected(false)
        // 1008 = policy violation (auth failure)
        if (event?.code === 1008) {
          localStorage.removeItem('zorali_token')
          showToast('Session expired — please reload to log in again.', 'error', 8000)
        }
      },
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
              ? {
                  ...m,
                  streaming: false,
                  stopped: !!msg.stopped,
                  meta: {
                    latency_ms: msg.latency_ms,
                    provider: msg.provider,
                    citation_count: (msg.citations || []).length,
                  },
                  citations: msg.citations || [],
                  web_citations: msg.web_citations || [],
                }
              : m
          ))
          if (speakRepliesRef.current && !msg.stopped) {
            setMessages(prev => {
              const last = prev[prev.length - 1]
              if (last?.role === 'assistant' && last.content) speak(last.content)
              return prev
            })
          }
          loadSessions()
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
  }, [sessionKey, loadSessions])

  // Auto-scroll
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // ── Send / stop / regenerate ──────────────────────────────────────────────
  function send(customText, { regenerate = false } = {}) {
    const text = (customText || input).trim()
    if (!text) return
    setInput('')
    window.speechSynthesis?.cancel()
    const images = regenerate ? [] : attachedImages
    setMessages(prev => [
      ...prev,
      ...(regenerate ? [] : [{ role: 'user', content: text, images: images.map(i => i.data) }]),
      { role: 'assistant', content: '', streaming: true },
    ])
    socketRef.current?.send({
      mode,
      message: text,
      project_id: activeProjectId,
      model: selectedModel,
      local_first: localFirst,
      deep_research: deepResearch,
      attachments: [
        ...attachedFiles,
        ...images.map(i => ({ type: 'image', name: i.name, data: i.data })),
      ],
      regenerate,
    })
    if (images.length) setAttachedImages([])
  }

  function stopGeneration() {
    socketRef.current?.send({ mode: 'stop' })
  }

  function regenerate() {
    const lastUser = [...messages].reverse().find(m => m.role === 'user')
    if (!lastUser) return
    // Drop the trailing assistant answer locally; the backend drops its copy.
    setMessages(prev => {
      const copy = [...prev]
      if (copy[copy.length - 1]?.role === 'assistant') copy.pop()
      return copy
    })
    send(lastUser.content, { regenerate: true })
  }

  // ── Project actions ───────────────────────────────────────────────────────
  async function handleAddProject(name) {
    setShowNewProject(false)
    try {
      const project = await apiPost('/api/project', { name, description: '' })
      setProjects(prev => [...prev, project])
      switchProject(project.id)
      showToast(`Project "${name}" created!`, 'success')
    } catch (e) {
      showToast(`Failed to create project: ${e.message}`, 'error')
    }
  }

  function switchProject(projectId) {
    if (projectId === activeProjectId) return
    setActiveProjectId(projectId)
    newChat()
  }

  async function saveProjectInstructions(instructions) {
    const project = settingsProject
    setSettingsProject(null)
    try {
      const updated = await apiPatch(`/api/project/${project.id}`, { system_prompt: instructions })
      setProjects(prev => prev.map(p => (p.id === updated.id ? updated : p)))
      showToast('Custom instructions saved', 'success')
    } catch (e) {
      showToast(`Failed to save instructions: ${e.message}`, 'error')
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
        setAttachedFiles(prev => [...prev, { name: file.name, id: result.id, status: result.indexing_status }])
        const statusLabel = result.indexing_status === 'queued' ? 'queued for indexing' : result.indexing_status === 'ready' ? 'indexed' : result.indexing_status
        showToast(`✓ ${file.name} uploaded — ${statusLabel}`, 'success')
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

  // ── Image attach (vision) ────────────────────────────────────────────────
  function handleImageSelect(e) {
    const files = Array.from(e.target.files || [])
    for (const file of files.slice(0, 4)) {
      if (file.size > 5 * 1024 * 1024) {
        showToast(`${file.name} is too large (max 5 MB)`, 'error')
        continue
      }
      const reader = new FileReader()
      reader.onload = () => {
        setAttachedImages(prev => [...prev, { name: file.name, data: reader.result }])
        showToast(`🖼 ${file.name} attached — sent with your next message`, 'success')
      }
      reader.readAsDataURL(file)
    }
    e.target.value = ''
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
    if (name === 'deepSearch') setPanelData({ info: 'Search Preview: sends your query to the agent for web-assisted answers. Full source ranking, deduplication, and citation mapping are planned for a future release.' })
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
      await apiPost('/api/memory', { project_id: activeProjectId, text: input.trim() })
      showToast('Memory saved', 'success')
      if (panel === 'memory') loadMemory()
    } catch (e) { showToast(`Memory save failed: ${e.message}`, 'error') }
  }

  async function searchMemory() {
    try {
      const data = await apiGet(`/api/memory/semantic-search?project_id=${activeProjectId}&q=${encodeURIComponent(memoryQuery || 'project')}`)
      setPanelData({ type: 'memory_search', ...data })
    } catch (e) { showToast(`Memory search failed: ${e.message}`, 'error') }
  }

  async function deleteMemory(id) {
    await apiDelete(`/api/memory/${id}`)
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

  async function runArtifact(artifactId) {
    try {
      const result = await apiPost(`/api/artifacts/${artifactId}/run`, {})
      const text = [
        `exit=${result.returncode}`,
        result.stdout && `stdout:\n${result.stdout}`,
        result.stderr && `stderr:\n${result.stderr}`,
      ].filter(Boolean).join('\n')
      setPanelData(prev => ({ ...prev, runOutput: { artifactId, text } }))
    } catch (e) {
      showToast(`Run failed: ${e.message}`, 'error')
    }
  }

  // ─── Render ──────────────────────────────────────────────────────────────
  return (
    <div className="zorali-shell">
      {/* ── Sidebar ── */}
      <aside className="sidebar">
        <div className="brand">
          <img src={logo} alt="Zorali" />
          <div className="brand-text">
            <strong>Zorali</strong>
            <span>Local J.A.R.V.I.S.</span>
          </div>
        </div>

        <button className="new-chat" onClick={newChat}>+ New chat</button>
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
              onClick={() => switchProject(p.id)}
            >
              <span className="project-name">▣ {p.name}</span>
              {p.id === activeProjectId && (
                <button
                  className="project-gear"
                  title="Custom instructions"
                  onClick={e => { e.stopPropagation(); setSettingsProject(p) }}
                >⚙</button>
              )}
            </div>
          ))}
        </section>

        <section>
          <div className="section-title">Recent</div>
          {sessions.length === 0 && (
            <div className="recent-item" style={{ opacity: 0.55, cursor: 'default' }}>No conversations yet</div>
          )}
          {sessions.slice(0, 12).map(s => (
            <div
              key={s.session_id}
              className={`recent-item${s.session_id === sessionKey ? ' active' : ''}`}
              title={s.preview}
              onClick={() => openSession(s.session_id)}
            >
              {s.preview || 'New conversation'}
            </div>
          ))}
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
            <img src={logo} alt="Zorali" className="topbar-logo" />
            <div>
              <h1>Zorali</h1>
              <p>Chat · Code · Research · Project Status · Safe Tools</p>
            </div>
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
            {availableModels.map(m => (
              <option key={m} value={m}>{m} (Local)</option>
            ))}
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
              <img src={logo} alt="Zorali" />
              <h2>How can Zorali help?</h2>
              <p>Choose a starter or ask anything about your project.</p>
              <div className="cards">
                {SUGGESTIONS.map(([icon, title, prompt]) => (
                  <button
                    key={title}
                    className="card-btn"
                    onClick={() => (title === 'Voice mode' ? toggleVoiceInput() : send(prompt))}
                  >
                    <span className="card-icon">{icon}</span>
                    <strong>{title}</strong>
                    <small>{title === 'Voice mode' ? 'Speak to Zorali (mic)' : prompt}</small>
                  </button>
                ))}
              </div>
            </div>
          )}
          {messages.map((m, i) => (
            <Message
              key={i}
              message={m}
              canRegenerate={!isStreaming && i === messages.length - 1 && m.role === 'assistant'}
              onRegenerate={regenerate}
              onSpeak={'speechSynthesis' in window ? speak : null}
            />
          ))}
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
            <button
              className={`toolbar-btn${listening ? ' mode-active' : ''}`}
              onClick={toggleVoiceInput}
              title="Voice input (speech-to-text)"
            >{listening ? '🔴 Listening…' : '🎙 Voice'}</button>
            <button
              className={`toolbar-btn${speakReplies ? ' mode-active' : ''}`}
              onClick={toggleSpeakReplies}
              title="Read replies aloud"
            >{speakReplies ? '🔊 Speaking on' : '🔈 Speak replies'}</button>
            <button className="toolbar-btn" onClick={() => imageInputRef.current?.click()} title="Attach an image (vision models)">🖼 Image</button>
            <button className="toolbar-btn" onClick={() => setMode('task')}>💻 Code</button>
            <input
              ref={fileInputRef}
              type="file"
              style={{ display: 'none' }}
              multiple
              accept=".txt,.md,.json,.csv,.py,.js,.ts,.jsx,.tsx,.html,.css,.toml,.yaml,.yml,.xml,.sh,.pdf"
              onChange={handleFileSelect}
            />
            <input
              ref={imageInputRef}
              type="file"
              style={{ display: 'none' }}
              multiple
              accept="image/*"
              onChange={handleImageSelect}
            />
          </div>

          {(attachedFiles.length > 0 || attachedImages.length > 0) && (
            <div className="file-pills">
              {attachedFiles.map(f => (
                <span key={f.id} className="file-pill">
                  📄 {f.name}
                  <button onClick={() => removeAttachedFile(f.id, f.name)} title="Remove">✕</button>
                </span>
              ))}
              {attachedImages.map((img, i) => (
                <span key={`img-${i}`} className="file-pill">
                  🖼 {img.name}
                  <button onClick={() => setAttachedImages(prev => prev.filter((_, j) => j !== i))} title="Remove">✕</button>
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
                if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); if (!isStreaming) send() }
              }}
              placeholder={listening ? 'Listening… speak now' : 'Message Zorali…'}
            />
            {isStreaming
              ? <button className="send-btn stop" onClick={stopGeneration}>⏹ Stop</button>
              : <button className="send-btn" onClick={() => send()} disabled={!input.trim()}>Send</button>
            }
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
              {panel === 'deepSearch' && panelData?.info && (
                <p style={{ color: 'var(--zorali-muted)', fontSize: 13, lineHeight: 1.5 }}>{panelData.info}</p>
              )}

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
                            <div style={{ display: 'flex', gap: 8 }}>
                              <button className="artifact-save-btn" onClick={() => saveArtifact(a.id, panelData.editContent)}>
                                Save
                              </button>
                              <button className="artifact-save-btn" onClick={() => runArtifact(a.id)} title="Run latest saved version in the Python sandbox (requires CODE_EXECUTION_ENABLED)">
                                ▶ Run
                              </button>
                            </div>
                            {panelData.runOutput?.artifactId === a.id && (
                              <pre className="status-pre" style={{ maxHeight: 180, overflow: 'auto' }}>
                                {panelData.runOutput.text}
                              </pre>
                            )}
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
      {settingsProject && (
        <ProjectSettingsModal
          project={settingsProject}
          onSave={saveProjectInstructions}
          onCancel={() => setSettingsProject(null)}
        />
      )}
      <Toast toasts={toasts} />
    </div>
  )
}
