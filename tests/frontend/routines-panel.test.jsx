// The routines panel: create a schedule, see the bounds the server enforces,
// and see why a routine switched itself off.
//
// The interesting assertion is the last one — a routine that disabled itself
// must say so where its owner will look, because a scheduled thing that stops
// silently is worse than one that never ran.
import React from 'react'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import RoutinesPanel from '../../frontend/src/components/RoutinesPanel.jsx'

const ROUTINE = {
  id: 'r1',
  name: 'Morning brief',
  prompt: 'What changed?',
  schedule_kind: 'interval',
  interval_seconds: 3600,
  hour_utc: 8,
  enabled: true,
  last_status: 'completed',
  disabled_reason: '',
}

function mockApi(routines, { postFails = null } = {}) {
  return vi.fn(async (path, init = {}) => {
    const method = init.method || 'GET'
    if (method === 'POST' && postFails) {
      return {
        ok: false, status: postFails.status,
        headers: { get: () => 'application/json' },
        text: async () => postFails.body,
        json: async () => JSON.parse(postFails.body),
      }
    }
    const body = method === 'GET' ? routines : { ok: true }
    return {
      ok: true, status: 200,
      headers: { get: () => 'application/json' },
      json: async () => body,
      text: async () => JSON.stringify(body),
    }
  })
}

describe('RoutinesPanel', () => {
  beforeEach(() => {
    vi.stubGlobal('localStorage', { getItem: () => 'token', setItem: () => {}, removeItem: () => {} })
  })
  afterEach(() => { cleanup(); vi.unstubAllGlobals() })

  it('lists a routine with its schedule in words', async () => {
    vi.stubGlobal('fetch', mockApi([ROUTINE]))

    render(<RoutinesPanel onClose={() => {}} />)

    expect(await screen.findByText('Morning brief')).toBeTruthy()
    expect(screen.getByText(/every 1h/)).toBeTruthy()
  })

  it('says when there are none rather than showing an empty box', async () => {
    vi.stubGlobal('fetch', mockApi([]))

    render(<RoutinesPanel onClose={() => {}} />)

    expect(await screen.findByText(/No routines yet/)).toBeTruthy()
  })

  it('surfaces why a routine disabled itself', async () => {
    // The whole point of the failure limit: the owner must be able to find
    // out why it stopped, not just that it did.
    vi.stubGlobal('fetch', mockApi([{
      ...ROUTINE,
      enabled: false,
      disabled_reason: 'disabled after 3 consecutive failures; last error: provider down',
    }]))

    render(<RoutinesPanel onClose={() => {}} />)

    expect(await screen.findByText(/3 consecutive failures/)).toBeTruthy()
  })

  it('shows the server’s bound verbatim when a schedule is refused', async () => {
    // The server owns the floor; the panel must not invent a friendlier
    // message that might not be true.
    vi.stubGlobal('fetch', mockApi([], {
      postFails: { status: 422, body: 'interval_seconds must be at least 300' },
    }))
    render(<RoutinesPanel onClose={() => {}} />)
    await screen.findByText(/No routines yet/)
    fireEvent.change(screen.getByLabelText('Routine name'), { target: { value: 'too eager' } })
    fireEvent.change(screen.getByLabelText('Routine prompt'), { target: { value: 'go' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add' }))

    await waitFor(() => expect(screen.getByText(/at least 300/)).toBeTruthy())
  })

  it('renders a daily routine as its hour', async () => {
    vi.stubGlobal('fetch', mockApi([{ ...ROUTINE, schedule_kind: 'daily', hour_utc: 7 }]))

    render(<RoutinesPanel onClose={() => {}} />)

    expect(await screen.findByText(/daily at 07:00 UTC/)).toBeTruthy()
  })
})
