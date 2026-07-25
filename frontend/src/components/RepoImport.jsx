import React, { useCallback, useEffect, useRef, useState } from 'react'
import { apiGet, apiPost } from '../api/httpClient.js'

const POLL_MS = 2000
const ACTIVE = new Set(['queued', 'cloning', 'importing'])

// GitHub repository import (capability map U6). Kicks off the import, then
// polls the import row until it settles, so the user sees progress and the
// per-file outcome rather than a spinner that means nothing.
export default function RepoImport({ projectId, onImported, onError }) {
  const [repo, setRepo] = useState('')
  const [ref, setRef] = useState('')
  const [token, setToken] = useState('')
  const [current, setCurrent] = useState(null)
  const [busy, setBusy] = useState(false)
  const timerRef = useRef(null)

  const stopPolling = useCallback(() => {
    if (timerRef.current) clearInterval(timerRef.current)
    timerRef.current = null
  }, [])

  useEffect(() => stopPolling, [stopPolling])

  const poll = useCallback((importId) => {
    stopPolling()
    timerRef.current = setInterval(async () => {
      try {
        const record = await apiGet(`/api/project/${projectId}/imports/${importId}`)
        setCurrent(record)
        if (!ACTIVE.has(record.status)) {
          stopPolling()
          setBusy(false)
          if (record.status === 'completed') onImported?.(record)
          else onError?.(record.error || 'Import failed')
        }
      } catch (err) {
        stopPolling()
        setBusy(false)
        onError?.(err.message)
      }
    }, POLL_MS)
  }, [projectId, onImported, onError, stopPolling])

  async function startImport(e) {
    e.preventDefault()
    if (!repo.trim() || busy) return
    setBusy(true)
    try {
      const body = { repo: repo.trim() }
      if (ref.trim()) body.ref = ref.trim()
      if (token.trim()) body.token = token.trim()
      const record = await apiPost(`/api/project/${projectId}/import/github`, body)
      // The token is never kept client-side after the request either.
      setToken('')
      setCurrent(record)
      poll(record.id)
    } catch (err) {
      setBusy(false)
      onError?.(err.message)
    }
  }

  return (
    <div className="repo-import">
      <form className="repo-import-form" onSubmit={startImport}>
        <input
          value={repo}
          onChange={e => setRepo(e.target.value)}
          placeholder="owner/repo or https://github.com/owner/repo"
          aria-label="Repository"
        />
        <input
          value={ref}
          onChange={e => setRef(e.target.value)}
          placeholder="branch (optional)"
          aria-label="Branch or tag"
        />
        <input
          value={token}
          onChange={e => setToken(e.target.value)}
          type="password"
          placeholder="token (private repos)"
          aria-label="Access token"
        />
        <button className="pill-btn" type="submit" disabled={busy || !repo.trim()}>
          {busy ? 'Importing…' : 'Import repo'}
        </button>
      </form>

      {current && (
        <div className="repo-import-status">
          <span className={`goal-status ${current.status}`}>{current.status}</span>
          <span>{current.source}{current.ref ? `@${current.ref}` : ''}</span>
          <span className="repo-import-counts">
            {current.imported_files} imported
            {current.skipped_files ? ` · ${current.skipped_files} skipped` : ''}
            {current.failed_files ? ` · ${current.failed_files} failed` : ''}
          </span>
          {current.error && <div className="goal-step-error">{current.error}</div>}
        </div>
      )}
    </div>
  )
}
