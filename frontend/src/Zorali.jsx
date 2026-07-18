import React, { useCallback, useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeHighlight from 'rehype-highlight'
import rehypeKatex from 'rehype-katex'
import 'katex/dist/katex.min.css'
import 'highlight.js/styles/github-dark.min.css'
import logo from './assets/zorali-logo.png'
import { createZoraliSocket } from './api/zoraliSocket.js'
import { apiGet, apiPost, apiPut, apiPatch, apiUpload, apiDelete } from './api/httpClient.js'

// ─── Suggestion cards ─────────────────────────────────────────────────────────
const SUGGESTIONS = [
  ['💻', 'Write code', 'Create a React component for a dashboard'],
  ['🔎', 'Deep research', 'Research the best local AI stack for 2026'],
  ['🎨', 'Generate image', 'Generate an image prompt for Zorali branding'],
  ['📎', 'Analyze files', 'Explain the uploaded project files'],
  ['🧠', 'Project assistant', 'Scan this project and tell me what is broken'],
  ['🎙️', 'Voice mode', 'Start voice assistant mode'],
]

// ─── Markdown renderer (react-markdown; raw HTML is never rendered) ───────────
function extractText(node) {
  if (node == null) return ''
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  if (Array.isArray(node)) return node.map(extractText).join('')
  if (node.props?.children != null) return extractText(node.props.children)
  return ''
}

function CodeBlock({ lang, code, children }) {
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
      <pre>{children ?? code}</pre>
    </div>
  )
}

// Fenced blocks arrive as <pre><code class="language-x">…</code></pre>;
// route them through CodeBlock so the copy button survives, keeping the
// highlighted children and extracting raw text for the clipboard.
function MarkdownPre({ children }) {
  const child = Array.isArray(children) ? children[0] : children
  const className = child?.props?.className || ''
  const lang = (className.match(/language-([\w-]+)/) || [])[1] || 'text'
  return <CodeBlock lang={lang} code={extractText(child)}>{child}</CodeBlock>
}

function MarkdownLink({ href, children }) {
  return <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>
}

const MD_COMPONENTS = { pre: MarkdownPre, a: MarkdownLink }
const REMARK_PLUGINS = [remarkGfm, remarkMath]
const REHYPE_PLUGINS = [rehypeHighlight, rehypeKatex]

function Markdown({ text }) {
  return (
    <ReactMarkdown
      remarkPlugins={REMARK_PLUGINS}
      rehypePlugins={REHYPE_PLUGINS}
      components={MD_COMPONENTS}
    >
      {text}
    </ReactMarkdown>
  )
}

// ─── Reasoning models: <think>…</think> → collapsible block ──────────────────
export function splitThinking(text) {
  if (!/<think>/i.test(text || '')) return { thinking: '', answer: text || '' }
  const closed = [...text.matchAll(/<think>([\s\S]*?)<\/think>/gi)].map(m => m[1].trim())
  let answer = text.replace(/<think>[\s\S]*?<\/think>/gi, '')
  const open = answer.match(/<think>[\s\S]*$/i)
  if (open) {
    closed.push(open[0].replace(/^<think>/i, '').trim())
    answer = answer.slice(0, open.index)
  }
  return { thinking: closed.filter(Boolean).join('\n'), answer: answer.trim() }
}

// ─── Tool steps (agent tool calls rendered as inline chips) ────────────────────
const TOOL_LABELS = {
  web_search: ['Searching the web', '🌐'],
  document_search: ['Searching project files', '📄'],
  calculator: ['Calculating', '🧮'],
  code_execution: ['Running code', '💻'],
  file_read: ['Reading file', '📖'],
  file_write: ['Writing file', '✏️'],
}

function ToolSteps({ steps }) {
  if (!steps?.length) return null
  return (
    <div className="tool-steps">
      {steps.map((s, i) => {
        const [label, icon] = TOOL_LABELS[s.tool] || [s.tool, '🔧']
        return (
          <span
            key={i}
            className={`tool-chip${s.done ? (s.ok ? ' done' : ' failed') : ''}`}
            title={s.inputs ? JSON.stringify(s.inputs) : undefined}
          >
            {icon} {label}{s.done ? ` → ${s.summary}` : '…'}
          </span>
        )
      })}
    </div>
  )
}

// ─── Message component ─────────────────────────────────────────────────────────
function Message({ message, canRegenerate, onRegenerate, onSpeak, canEdit, onEdit }) {
  const isUser = message.role === 'user'
  const content = message.content || ''
  const citations = message.citations || []
  const webCitations = message.web_citations || []
  const images = message.images || []
  const [copied, setCopied] = useState(false)
  const { thinking, answer } = isUser ? { thinking: '', answer: content } : splitThinking(content)

  const copyMessage = () => {
    navigator.clipboard.writeText(answer).then(() => {
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
        {!isUser && <ToolSteps steps={message.steps} />}
        {!isUser && thinking && (
          <details className="thinking-block" open={message.streaming && !answer}>
            <summary>🧠 Thinking{message.streaming && !answer ? '…' : ''}</summary>
            <div className="thinking-text">{thinking}</div>
          </details>
        )}
        {isUser
          ? <div className="bubble-text"><p>{content}{message.streaming && <span className="stream-cursor" />}</p></div>
          : <div className="bubble-text">
              <Markdown text={answer} />
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
      {isUser && canEdit && (
        <div className="msg-actions">
          <button className="msg-action-btn" onClick={() => onEdit(content)} title="Edit and resend (replaces this exchange)">
            ✎ Edit
          </button>
        </div>
      )}
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
  // Model-driven tool use (web search, project files, …) — default ON.
  const [toolsEnabled, setToolsEnabled] = useState(true)
  const [ollamaOk, setOllamaOk] = useState(null)
  const [providerStatus, setProviderStatus] = useState(null)
  const socketRef = useRef(null)
  // Conversation (session) management — ChatGPT-style history in the sidebar
  const [sessionKey, setSessionKey] = useState(() => crypto.randomUUID())
  const [sessions, setSessions] = useState([])
  // Sidebar chat search: instant client-side filter over previews, replaced
  // by debounced server-side results (ILIKE over message content) when ready.
  const [sessionSearch, setSessionSearch] = useState('')
  const [searchResults, setSearchResults] = useState(null)
  // Edit & resend: the next send replaces the last user/assistant exchange.
  const [editingLast, setEditingLast] = useState(false)
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

  // Debounced server-side chat search over message content.
  useEffect(() => {
    const q = sessionSearch.trim()
    if (!q || !activeProjectId || activeProjectId === 'default') {
      setSearchResults(null)
      return
    }
    const timer = setTimeout(() => {
      apiGet(`/api/project/${activeProjectId}/search?q=${encodeURIComponent(q)}`)
        .then(rows => {
          const bySession = new Map()
          for (const r of rows) if (!bySession.has(r.session_id)) bySession.set(r.session_id, r)
          setSearchResults([...bySession.values()])
        })
        .catch(() => setSearchResults(null))
    }, 300)
    return () => clearTimeout(timer)
  }, [sessionSearch, activeProjectId])

  async function renameSession(s) {
    const next = window.prompt('Rename conversation', s.title || s.preview || '')
    if (next == null || !next.trim()) return
    try {
      await apiPatch(`/api/project/${activeProjectId}/sessions/${encodeURIComponent(s.session_id)}`, { title: next.trim() })
      loadSessions()
    } catch (e) { showToast(`Rename failed: ${e.message}`, 'error') }
  }

  async function deleteSession(s) {
    if (!window.confirm('Delete this conversation? Its messages are removed for good.')) return
    try {
      await apiDelete(`/api/project/${activeProjectId}/sessions/${encodeURIComponent(s.session_id)}`)
      if (s.session_id === sessionKey) newChat()
      loadSessions()
    } catch (e) { showToast(`Delete failed: ${e.message}`, 'error') }
  }

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
    // Never read the model's <think> chain of thought aloud.
    text = splitThinking(text).answer
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
        if (msg.type === 'tool_use') {
          setMessages(prev => {
            const copy = [...prev]
            const last = copy[copy.length - 1]
            if (last?.role === 'assistant' && last.streaming) {
              last.steps = [...(last.steps || []), { tool: msg.tool, inputs: msg.inputs, done: false }]
            }
            return copy
          })
        }
        if (msg.type === 'tool_result') {
          setMessages(prev => {
            const copy = [...prev]
            const last = copy[copy.length - 1]
            if (last?.role === 'assistant' && last.streaming) {
              const steps = [...(last.steps || [])]
              for (let i = steps.length - 1; i >= 0; i--) {
                if (steps[i].tool === msg.tool && !steps[i].done) {
                  steps[i] = { ...steps[i], done: true, summary: msg.summary, ok: msg.ok !== false }
                  break
                }
              }
              last.steps = steps
            }
            return copy
          })
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
    const editing = editingLast && !regenerate
    setInput('')
    setEditingLast(false)
    window.speechSynthesis?.cancel()
    const images = regenerate ? [] : attachedImages
    setMessages(prev => {
      let base = prev
      if (editing) {
        // Replace the last exchange locally; the backend drops its copy.
        const lastUserIdx = prev.map(m => m.role).lastIndexOf('user')
        if (lastUserIdx >= 0) base = prev.slice(0, lastUserIdx)
      }
      return [
        ...base,
        ...(regenerate ? [] : [{ role: 'user', content: text, images: images.map(i => i.data) }]),
        { role: 'assistant', content: '', streaming: true },
      ]
    })
    socketRef.current?.send({
      mode,
      message: text,
      project_id: activeProjectId,
      model: selectedModel,
      local_first: localFirst,
      deep_research: deepResearch,
      tools_enabled: toolsEnabled,
      edit_last: editing,
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
      const [data, pending] = await Promise.all([
        apiGet(`/api/project/${activeProjectId}/chats`),
        apiGet(`/api/memory/pending?project_id=${activeProjectId}`).catch(() => []),
      ])
      setPanelData({ type: 'memory', items: data, pending })
    } catch (e) {
      showToast(`Failed to load memory: ${e.message}`, 'error')
    } finally {
      setPanelLoading(false)
    }
  }

  async function acceptMemory(id) {
    try {
      await apiPost(`/api/memory/${id}/accept`, {})
      showToast('Memory saved', 'success')
      loadMemory()
    } catch (e) { showToast(`Accept failed: ${e.message}`, 'error') }
  }

  async function rejectMemory(id) {
    try {
      await apiPost(`/api/memory/${id}/reject`, {})
      loadMemory()
    } catch (e) { showToast(`Reject failed: ${e.message}`, 'error') }
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

  // Server-side results (message-content search) win once they arrive;
  // until then the client-side filter over titles/previews gives instant feedback.
  const shownSessions = searchResults != null
    ? searchResults.map(r => ({
        ...(sessions.find(s => s.session_id === r.session_id) || { session_id: r.session_id }),
        snippet: r.snippet,
      }))
    : sessionSearch.trim()
      ? sessions.filter(s =>
          ((s.title || '') + ' ' + (s.preview || '')).toLowerCase().includes(sessionSearch.trim().toLowerCase())
        )
      : sessions

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
        <input
          className="sidebar-search"
          placeholder="Search chats…"
          value={sessionSearch}
          onChange={e => setSessionSearch(e.target.value)}
        />

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
          {sessions.length > 0 && shownSessions.length === 0 && (
            <div className="recent-item" style={{ opacity: 0.55, cursor: 'default' }}>No matching chats</div>
          )}
          {shownSessions.slice(0, 12).map(s => (
            <div
              key={s.session_id}
              className={`recent-item${s.session_id === sessionKey ? ' active' : ''}`}
              title={s.snippet || s.preview}
              onClick={() => openSession(s.session_id)}
            >
              <span className="recent-label">{s.title || s.preview || s.snippet || 'New conversation'}</span>
              <span className="recent-actions" onClick={e => e.stopPropagation()}>
                <button title="Rename" onClick={() => renameSession(s)}>✎</button>
                <button title="Delete" onClick={() => deleteSession(s)}>🗑</button>
              </span>
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
          <button
            className={`conn-btn${toolsEnabled ? ' connected' : ''}`}
            onClick={() => setToolsEnabled(v => !v)}
            title="Let the model call tools mid-answer (web search, project files, calculator)"
          >
            {toolsEnabled ? '●' : '○'} Tools
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
              canEdit={!isStreaming && m.role === 'user' && i === messages.map(x => x.role).lastIndexOf('user')}
              onEdit={content => { setInput(content); setEditingLast(true) }}
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

          {editingLast && (
            <div className="file-pills">
              <span className="file-pill">
                ✎ Editing last message — sending replaces the previous answer
                <button onClick={() => { setEditingLast(false); setInput('') }} title="Cancel edit">✕</button>
              </span>
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
              {panel === 'memory' && panelData?.pending?.length > 0 && (
                <div style={{ marginBottom: 12 }}>
                  <div className="section-title">Pending memories — review</div>
                  {panelData.pending.map(m => (
                    <div key={m.id} className="memory-item">
                      <div className="memory-content">{m.text}</div>
                      <div style={{ display: 'flex', gap: 6, marginTop: 4 }}>
                        <button className="toolbar-btn" onClick={() => acceptMemory(m.id)}>✓ Accept</button>
                        <button className="toolbar-btn" onClick={() => rejectMemory(m.id)}>✕ Reject</button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
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
