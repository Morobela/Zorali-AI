import React, { useEffect, useState } from 'react'

import { apiDelete, apiGet, apiPatch, apiPost } from '../api/httpClient.js'

// User-configurable routines: a schedule plus a prompt that runs without you.
// The built-in routines (reality scan, nightly self-check, nightly backup) are
// the deployment's; these are the account's.
//
// Bounds are shown, not hidden: the interval floor, the per-run ceiling and why
// a routine disabled itself all appear here, because a scheduled thing that
// spends money should not be able to surprise the person who created it.

const EMPTY = { name: '', prompt: '', schedule_kind: 'interval', interval_seconds: 3600, hour_utc: 8 }

function describeSchedule(routine) {
  if (routine.schedule_kind === 'daily') return `daily at ${String(routine.hour_utc).padStart(2, '0')}:00 UTC`
  const seconds = routine.interval_seconds
  if (seconds % 3600 === 0) return `every ${seconds / 3600}h`
  if (seconds % 60 === 0) return `every ${seconds / 60}m`
  return `every ${seconds}s`
}

export default function RoutinesPanel({ onClose }) {
  const [routines, setRoutines] = useState([])
  const [draft, setDraft] = useState(EMPTY)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function refresh() {
    try {
      setRoutines(await apiGet('/api/routines'))
    } catch (err) {
      setError(String(err.message || err))
    }
  }

  useEffect(() => { refresh() }, [])

  async function create(event) {
    event.preventDefault()
    setError(''); setBusy(true)
    try {
      await apiPost('/api/routines', {
        ...draft,
        interval_seconds: Number(draft.interval_seconds),
        hour_utc: Number(draft.hour_utc),
      })
      setDraft(EMPTY)
      await refresh()
    } catch (err) {
      // The server owns the bounds; show exactly what it said rather than
      // guessing at a friendlier version that might not be true.
      setError(String(err.message || err))
    } finally {
      setBusy(false)
    }
  }

  async function toggle(routine) {
    setError('')
    try {
      await apiPatch(`/api/routines/${routine.id}`, { enabled: !routine.enabled })
      await refresh()
    } catch (err) {
      setError(String(err.message || err))
    }
  }

  async function runNow(routine) {
    setError(''); setBusy(true)
    try {
      await apiPost(`/api/routines/${routine.id}/run`)
      await refresh()
    } catch (err) {
      setError(String(err.message || err))
    } finally {
      setBusy(false)
    }
  }

  async function remove(routine) {
    setError('')
    try {
      await apiDelete(`/api/routines/${routine.id}`)
      await refresh()
    } catch (err) {
      setError(String(err.message || err))
    }
  }

  return (
    <div className="routines-panel" role="dialog" aria-label="Routines">
      <div className="routines-head">
        <strong>Routines</strong>
        <button className="notif-link" onClick={onClose} aria-label="Close routines">✕</button>
      </div>

      <form className="routine-form" onSubmit={create}>
        <input
          aria-label="Routine name"
          placeholder="Morning brief"
          value={draft.name}
          onChange={e => setDraft({ ...draft, name: e.target.value })}
          required
        />
        <textarea
          aria-label="Routine prompt"
          placeholder="What changed in my project since yesterday?"
          value={draft.prompt}
          onChange={e => setDraft({ ...draft, prompt: e.target.value })}
          required
        />
        <div className="routine-schedule">
          <select
            aria-label="Schedule kind"
            value={draft.schedule_kind}
            onChange={e => setDraft({ ...draft, schedule_kind: e.target.value })}
          >
            <option value="interval">every…</option>
            <option value="daily">daily at…</option>
          </select>
          {draft.schedule_kind === 'interval' ? (
            <input
              aria-label="Interval in seconds"
              type="number"
              min="300"
              value={draft.interval_seconds}
              onChange={e => setDraft({ ...draft, interval_seconds: e.target.value })}
            />
          ) : (
            <input
              aria-label="Hour UTC"
              type="number"
              min="0"
              max="23"
              value={draft.hour_utc}
              onChange={e => setDraft({ ...draft, hour_utc: e.target.value })}
            />
          )}
          <button type="submit" disabled={busy}>Add</button>
        </div>
      </form>

      {error && <div className="routine-error">{error}</div>}

      {routines.length === 0 && (
        <div className="notif-empty">No routines yet. Add one and Zorali will run it on its own.</div>
      )}

      {routines.map(routine => (
        <div key={routine.id} className={`routine-row${routine.enabled ? '' : ' disabled'}`}>
          <div className="routine-row-main">
            <div className="routine-title">{routine.name}</div>
            <div className="routine-meta">
              {describeSchedule(routine)}
              {routine.last_status && ` · last run ${routine.last_status}`}
            </div>
            {routine.disabled_reason && (
              <div className="routine-warning">{routine.disabled_reason}</div>
            )}
          </div>
          <span className="routine-actions">
            <button className="notif-link" onClick={() => runNow(routine)} disabled={busy} title="Run now">▶</button>
            <button className="notif-link" onClick={() => toggle(routine)} title={routine.enabled ? 'Disable' : 'Enable'}>
              {routine.enabled ? '⏸' : '▶︎'}
            </button>
            <button className="notif-link" onClick={() => remove(routine)} title="Delete">🗑</button>
          </span>
        </div>
      ))}
    </div>
  )
}
