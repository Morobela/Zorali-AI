// RepoImport: starts a GitHub import and polls the import row to completion
// (capability map U6).
import React from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import RepoImport from '../../frontend/src/components/RepoImport.jsx'

const QUEUED = {
  id: 'imp1', project_id: 'p1', source: 'Morobela/Zorali-AI', ref: '',
  status: 'queued', imported_files: 0, skipped_files: 0, failed_files: 0, files: [], error: '',
}
const DONE = { ...QUEUED, status: 'completed', imported_files: 214, skipped_files: 30 }

function jsonResponse(data, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: (name) => (name.toLowerCase() === 'content-type' ? 'application/json' : null) },
    json: async () => data,
    text: async () => JSON.stringify(data),
  }
}

let calls

beforeEach(() => {
  calls = []
  vi.useFakeTimers({ shouldAdvanceTime: true })
  vi.stubGlobal('fetch', vi.fn(async (path, init = {}) => {
    const method = init.method || 'GET'
    calls.push({ method, path, body: init.body ? JSON.parse(init.body) : undefined })
    if (method === 'POST' && path === '/api/project/p1/import/github') return jsonResponse(QUEUED)
    if (method === 'GET' && path === '/api/project/p1/imports/imp1') return jsonResponse(DONE)
    return jsonResponse({ detail: `unmocked ${method} ${path}` }, 404)
  }))
})

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('RepoImport', () => {
  it('submits the repository and reports progress to completion', async () => {
    const onImported = vi.fn()
    render(<RepoImport projectId="p1" onImported={onImported} />)

    fireEvent.change(screen.getByLabelText('Repository'), {
      target: { value: 'Morobela/Zorali-AI' },
    })
    fireEvent.click(screen.getByText('Import repo'))

    // The POST carries the repository; polling then settles the status.
    await vi.waitFor(() => {
      expect(calls.some(c => c.method === 'POST' && c.body?.repo === 'Morobela/Zorali-AI')).toBe(true)
    })
    await vi.advanceTimersByTimeAsync(2100)
    await vi.waitFor(() => expect(onImported).toHaveBeenCalled())
    expect(screen.getByText('completed')).toBeTruthy()
    expect(screen.getByText(/214 imported/)).toBeTruthy()
  })

  it('sends branch and token only when provided, and clears the token', async () => {
    render(<RepoImport projectId="p1" />)
    fireEvent.change(screen.getByLabelText('Repository'), { target: { value: 'o/r' } })
    fireEvent.change(screen.getByLabelText('Branch or tag'), { target: { value: 'main' } })
    fireEvent.change(screen.getByLabelText('Access token'), { target: { value: 'ghp_secret' } })
    fireEvent.click(screen.getByText('Import repo'))

    await vi.waitFor(() => expect(calls.some(c => c.method === 'POST')).toBe(true))
    const post = calls.find(c => c.method === 'POST')
    expect(post.body).toEqual({ repo: 'o/r', ref: 'main', token: 'ghp_secret' })
    // The token is not left sitting in the form after submission.
    await vi.waitFor(() => expect(screen.getByLabelText('Access token').value).toBe(''))
  })

  it('does not submit an empty repository', () => {
    render(<RepoImport projectId="p1" />)
    expect(screen.getByText('Import repo').disabled).toBe(true)
    expect(calls.length).toBe(0)
  })
})
