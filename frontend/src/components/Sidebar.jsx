import React, { useState } from 'react'
import logo from '../assets/zorali-logo.png'

export default function Sidebar({ projects, activeProjectId, onSelectProject, onAddProject, connected }) {
  const [showInput, setShowInput] = useState(false)
  const [newName, setNewName] = useState('')

  function handleAdd() {
    if (!newName.trim()) return
    onAddProject(newName.trim())
    setNewName('')
    setShowInput(false)
  }

  return (
    <aside className="sidebar">
      <div className="brand">
        <img src={logo} alt="Zorali" />
        <div className="brand-text">
          <strong>Zorali</strong>
          <span>Local J.A.R.V.I.S.</span>
        </div>
      </div>

      <input className="sidebar-search" placeholder="Search chats…" />

      <section>
        <div className="section-title">
          Projects
          <button onClick={() => setShowInput(v => !v)} title="New project">+</button>
        </div>
        {showInput && (
          <div style={{ display: 'flex', gap: 4, marginBottom: 4 }}>
            <input
              className="sidebar-search"
              style={{ flex: 1 }}
              autoFocus
              placeholder="Project name"
              value={newName}
              onChange={e => setNewName(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleAdd()}
            />
            <button style={{ border: 'none', background: 'var(--zorali-green)', color: '#fff', borderRadius: 8, padding: '4px 10px', fontSize: 13 }} onClick={handleAdd}>✓</button>
          </div>
        )}
        {(projects || []).map(p => (
          <div
            key={p.id}
            className={`project-item${p.id === activeProjectId ? ' active' : ''}`}
            onClick={() => onSelectProject(p.id)}
          >
            ▣ {p.name}
          </div>
        ))}
      </section>

      <section>
        <div className="section-title">Recent</div>
        <div className="recent-item active">Zorali build</div>
        <div className="recent-item">Website deployment</div>
        <div className="recent-item">Research notes</div>
      </section>

      <div className="sidebar-bottom">
        <span className={`conn-dot ${connected ? 'online' : 'offline'}`}>●</span>
        <span>{connected ? 'Connected' : 'Disconnected'}</span>
      </div>
    </aside>
  )
}
