// Frontend smoke tests: mount the real Zorali app with the network mocked and
// exercise the project-settings save path (PATCH /api/project/{id}) and the
// sidebar chat search. Run from frontend/: npm test
import React from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import Zorali from '../../frontend/src/Zorali.jsx'

const PROJECT = { id: 'p1', name: 'Test Project', description: '', system_prompt: '' }
const SESSIONS = [
  { session_id: 's1', preview: 'alpha rocket telemetry', message_count: 2 },
  { session_id: 's2', preview: 'beta budget planning', message_count: 4 },
]

function jsonResponse(data, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: (name) => (name.toLowerCase() === 'content-type' ? 'application/json' : null) },
    json: async () => data,
    text: async () => JSON.stringify(data),
  }
}

// Minimal WebSocket stand-in: the chat socket is irrelevant to these tests,
// it just must not crash on construction.
class FakeWebSocket {
  static CONNECTING = 0
  static OPEN = 1
  static CLOSING = 2
  static CLOSED = 3
  constructor(url) {
    this.url = url
    this.readyState = FakeWebSocket.CONNECTING
  }
  send() {}
  close() {}
}

let fetchCalls

beforeEach(() => {
  fetchCalls = []
  vi.stubGlobal('WebSocket', FakeWebSocket)
  if (!Element.prototype.scrollIntoView) Element.prototype.scrollIntoView = () => {}
  vi.stubGlobal('fetch', vi.fn(async (path, init = {}) => {
    const method = init.method || 'GET'
    const body = init.body ? JSON.parse(init.body) : undefined
    fetchCalls.push({ method, path, body })
    if (method === 'POST' && path === '/api/ws-ticket') return jsonResponse({ ticket: 'test-ticket' })
    if (method === 'GET' && path === '/api/project') return jsonResponse([PROJECT])
    if (method === 'GET' && path === '/api/ollama/health') return jsonResponse({ ok: true, models: ['llama3.2:1b'] })
    if (method === 'GET' && path === '/api/providers/status') return jsonResponse({ last_used_provider: 'ollama', fallback_used: false })
    if (method === 'GET' && path === `/api/project/${PROJECT.id}/sessions`) return jsonResponse(SESSIONS)
    if (method === 'PATCH' && path === `/api/project/${PROJECT.id}`) return jsonResponse({ ...PROJECT, ...body })
    return jsonResponse({ detail: `unmocked ${method} ${path}` }, 404)
  }))
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('Zorali app smoke', () => {
  it('saves custom instructions through PATCH /api/project/{id}', async () => {
    render(<Zorali />)
    await screen.findByText(`▣ ${PROJECT.name}`)

    fireEvent.click(await screen.findByTitle('Custom instructions'))
    const textarea = screen.getByPlaceholderText(/Answer concisely/i)
    fireEvent.change(textarea, { target: { value: 'Address me as Commander.' } })
    fireEvent.click(screen.getByText('Save'))

    await screen.findByText('Custom instructions saved')
    const patch = fetchCalls.find(c => c.method === 'PATCH')
    expect(patch).toBeTruthy()
    expect(patch.path).toBe(`/api/project/${PROJECT.id}`)
    expect(patch.body).toEqual({ system_prompt: 'Address me as Commander.' })
  })

  it('filters the sidebar session list as the user types in search', async () => {
    render(<Zorali />)
    await screen.findByText('alpha rocket telemetry')
    await screen.findByText('beta budget planning')

    const search = screen.getByPlaceholderText('Search chats…')
    fireEvent.change(search, { target: { value: 'rocket' } })
    expect(screen.getByText('alpha rocket telemetry')).toBeTruthy()
    expect(screen.queryByText('beta budget planning')).toBeNull()

    fireEvent.change(search, { target: { value: 'no such conversation' } })
    await screen.findByText('No matching chats')

    fireEvent.change(search, { target: { value: '' } })
    await screen.findByText('beta budget planning')
  })
})
