import React, { useState } from 'react'

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
        <span>{lang || 'code'}</span>
        <button className={`copy-btn${copied ? ' copied' : ''}`} onClick={copy}>
          {copied ? '✓ Copied' : '⎘ Copy'}
        </button>
      </div>
      <pre>{code}</pre>
    </div>
  )
}

function inlineFormat(text) {
  const parts = []
  const regex = /(`[^`]+`|\*\*[^*]+\*\*|__[^_]+__)/g
  let last = 0, m
  while ((m = regex.exec(text)) !== null) {
    if (m.index > last) parts.push(text.slice(last, m.index))
    const token = m[0]
    if (token.startsWith('`')) parts.push(<code key={m.index}>{token.slice(1, -1)}</code>)
    else parts.push(<strong key={m.index}>{token.slice(2, -2)}</strong>)
    last = m.index + token.length
  }
  if (last < text.length) parts.push(text.slice(last))
  return parts
}

function renderMarkdown(text) {
  const lines = text.split('\n')
  const elements = []
  let i = 0
  while (i < lines.length) {
    const line = lines[i]
    const codeMatch = line.match(/^```(\w*)$/)
    if (codeMatch) {
      const lang = codeMatch[1]
      const codeLines = []
      i++
      while (i < lines.length && !lines[i].startsWith('```')) { codeLines.push(lines[i]); i++ }
      elements.push(<CodeBlock key={`code-${i}`} lang={lang} code={codeLines.join('\n')} />)
      i++
      continue
    }
    if (line.startsWith('- ') || line.startsWith('* ')) {
      const items = []
      while (i < lines.length && (lines[i].startsWith('- ') || lines[i].startsWith('* '))) {
        items.push(lines[i].slice(2)); i++
      }
      elements.push(<ul key={`ul-${i}`}>{items.map((it, j) => <li key={j}>{inlineFormat(it)}</li>)}</ul>)
      continue
    }
    if (line.trim() === '') { i++; continue }
    elements.push(<p key={`p-${i}`}>{inlineFormat(line)}</p>)
    i++
  }
  return elements
}

export default function ChatMessage({ message }) {
  if (!message) return null
  const isUser = message.role === 'user'
  const citations = message.citations || []

  return (
    <div className={`message ${message.role}`}>
      <div className="bubble">
        {isUser
          ? <div className="bubble-text">
              <p>{message.content}{message.streaming && <span className="stream-cursor" />}</p>
            </div>
          : <div className="bubble-text">
              {renderMarkdown(message.content || '')}
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
      {message.meta && !isUser && message.meta.reasoning_depth && (
        <div className="msg-meta">
          {message.meta.reasoning_depth}
        </div>
      )}
    </div>
  )
}
