import { useState } from 'react'

export default function ProjectModal({ onConfirm, onCancel }) {
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
