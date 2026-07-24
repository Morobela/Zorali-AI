// NotificationBell: the U4 proactive surface. The badge reflects the unread
// count with no user action, the panel lists notifications, and mark-read
// hits the API and clears the badge.
import React from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import NotificationBell from '../../frontend/src/components/NotificationBell.jsx'

const NOTES = [
  {
    id: 'n1', kind: 'service_down', title: '[redis] service down',
    body: 'redis: up → down', read: false, created_at: '2026-07-24T09:00:00Z',
  },
  {
    id: 'n2', kind: 'dirty_changes_aging', title: '[git] dirty changes aging',
    body: '3 uncommitted change(s) sitting for 25.0h', read: true, created_at: '2026-07-23T08:00:00Z',
  },
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

let fetchCalls

beforeEach(() => {
  fetchCalls = []
  vi.stubGlobal('fetch', vi.fn(async (path, init = {}) => {
    const method = init.method || 'GET'
    fetchCalls.push({ method, path })
    if (method === 'GET' && path === '/api/notifications/unread-count') return jsonResponse({ unread: 1 })
    if (method === 'GET' && path === '/api/notifications?limit=50') return jsonResponse(NOTES)
    if (method === 'POST' && path === '/api/notifications/n1/read') return jsonResponse({ read: true })
    if (method === 'POST' && path === '/api/notifications/read-all') return jsonResponse({ marked: 1 })
    return jsonResponse({ detail: `unmocked ${method} ${path}` }, 404)
  }))
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('NotificationBell', () => {
  it('shows the unread badge without any user action', async () => {
    render(<NotificationBell />)
    expect(await screen.findByText('1')).toBeTruthy()
    expect(fetchCalls.some(c => c.path === '/api/notifications/unread-count')).toBe(true)
  })

  it('opens the panel, lists notifications and marks one read', async () => {
    render(<NotificationBell />)
    await screen.findByText('1')

    fireEvent.click(screen.getByTitle('Notifications'))
    expect(await screen.findByText('[redis] service down')).toBeTruthy()
    expect(screen.getByText('[git] dirty changes aging')).toBeTruthy()

    fireEvent.click(screen.getByTitle('Mark read'))
    await vi.waitFor(() => {
      expect(fetchCalls.some(c => c.method === 'POST' && c.path === '/api/notifications/n1/read')).toBe(true)
    })
    // Badge cleared: the only unread notification was acknowledged.
    await vi.waitFor(() => {
      expect(screen.queryByText('1')).toBeNull()
    })
  })
})
