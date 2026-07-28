// The client half of the chat WebSocket contract (schema version 1).
//
// The socket wrapper stamps `schema_version` and a `request_id` on every frame
// so no caller has to remember to. These tests pin that, plus the one piece of
// real logic: a control frame ("stop") carries the id of the turn it acts on
// rather than minting a new one.
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { SCHEMA_VERSION, createZoraliSocket } from '../../frontend/src/api/zoraliSocket.js'

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')

// Minimal WebSocket double: records what the client sends.
class FakeSocket {
  static instances = []
  constructor(url) {
    this.url = url
    this.readyState = 1 // OPEN
    this.sent = []
    FakeSocket.instances.push(this)
  }
  send(data) {
    this.sent.push(JSON.parse(data))
  }
  close() {
    this.readyState = 3
  }
}
FakeSocket.OPEN = 1

async function connectedSocket() {
  const socket = createZoraliSocket('session-1')
  // Let the async ticket exchange and WebSocket construction settle.
  await vi.waitFor(() => expect(FakeSocket.instances.length).toBe(1))
  FakeSocket.instances[0].onopen?.()
  return socket
}

describe('zoraliSocket frame envelope', () => {
  beforeEach(() => {
    FakeSocket.instances = []
    // jsdom already supplies window/localStorage; only the network and the
    // socket itself need standing in for.
    vi.stubGlobal('WebSocket', FakeSocket)
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: true,
      status: 200,
      headers: { get: () => 'application/json' },
      json: async () => ({ ticket: 'test-ticket' }),
      text: async () => '{"ticket":"test-ticket"}',
    })))
  })

  it('stamps the schema version and a request id on every frame', async () => {
    const socket = await connectedSocket()

    socket.send({ mode: 'chat', message: 'hello' })

    const [frame] = FakeSocket.instances[0].sent
    expect(frame.schema_version).toBe(SCHEMA_VERSION)
    expect(frame.request_id).toBeTruthy()
    // The fields the backend already reads are untouched.
    expect(frame.mode).toBe('chat')
    expect(frame.message).toBe('hello')
  })

  it('gives each turn its own request id', async () => {
    const socket = await connectedSocket()

    socket.send({ mode: 'chat', message: 'first' })
    socket.send({ mode: 'chat', message: 'second' })

    const [a, b] = FakeSocket.instances[0].sent
    expect(a.request_id).not.toBe(b.request_id)
  })

  it('sends stop under the id of the turn it interrupts', async () => {
    const socket = await connectedSocket()

    socket.send({ mode: 'chat', message: 'a long answer' })
    socket.send({ mode: 'stop' })

    const [turn, stop] = FakeSocket.instances[0].sent
    // A stop that minted its own id would be uncorrelatable with the answer
    // it cancels.
    expect(stop.request_id).toBe(turn.request_id)
  })

  it('lets an explicit request id from the caller win', async () => {
    const socket = await connectedSocket()

    socket.send({ mode: 'chat', message: 'hi', request_id: 'caller-chosen' })

    expect(FakeSocket.instances[0].sent[0].request_id).toBe('caller-chosen')
  })

  it('stamps frames queued before the socket opened', async () => {
    const socket = createZoraliSocket('session-2')
    socket.send({ mode: 'chat', message: 'queued early' })
    await vi.waitFor(() => expect(FakeSocket.instances.length).toBe(1))
    FakeSocket.instances[0].onopen?.()

    const [frame] = FakeSocket.instances[0].sent
    expect(frame.schema_version).toBe(SCHEMA_VERSION)
    expect(frame.request_id).toBeTruthy()
  })
})

describe('the two halves of the contract agree', () => {
  it('uses the same schema version as the backend', () => {
    const backend = fs.readFileSync(
      path.join(repoRoot, 'backend/app/api/ws_protocol.py'), 'utf8',
    )
    const match = backend.match(/^SCHEMA_VERSION\s*=\s*(\d+)/m)

    expect(match, 'SCHEMA_VERSION not found in ws_protocol.py').toBeTruthy()
    expect(Number(match[1])).toBe(SCHEMA_VERSION)
  })

  it('only handles frame types the backend can send', () => {
    const backend = fs.readFileSync(
      path.join(repoRoot, 'backend/app/api/ws_protocol.py'), 'utf8',
    )
    const declared = new Set(
      [...backend.matchAll(/^\s{4}"([a-z_]+)",\s*#/gm)].map((m) => m[1]),
    )
    expect(declared.size).toBeGreaterThan(0)

    const ui = fs.readFileSync(path.join(repoRoot, 'frontend/src/Zorali.jsx'), 'utf8')
    const handled = [...ui.matchAll(/msg\.type === '([a-z_]+)'/g)].map((m) => m[1])
    expect(handled.length).toBeGreaterThan(0)

    const unknown = handled.filter((name) => !declared.has(name))
    expect(unknown, `UI handles frames the backend never sends: ${unknown}`).toEqual([])
  })
})
