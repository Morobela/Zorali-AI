import { apiPost } from './httpClient.js'

// Must match backend/app/api/ws_protocol.py — the contract lives there and is
// documented in docs/API.md.
export const SCHEMA_VERSION = 1

function nextRequestId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID()
  return `req-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

// Opens the chat WebSocket using a single-use auth ticket. The JWT itself
// never appears in the URL (query strings end up in server access logs);
// instead we exchange it for a short-lived ticket over an authenticated POST,
// and the backend consumes that ticket on connect.
export function createZoraliSocket(sessionId, handlers = {}) {
  const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
  let ws = null
  let closed = false
  let lastRequestId = null
  const sendQueue = []

  ;(async () => {
    let ticket
    try {
      ;({ ticket } = await apiPost('/api/ws-ticket'))
    } catch (err) {
      // Could not authenticate (or the ticket store is down) — surface it the
      // same way as a policy-violation close so the app's auth handling runs.
      handlers.onClose?.({ code: 1008, reason: String(err) })
      return
    }
    if (closed) return
    const url = `${protocol}://${window.location.host}/ws/chat/${sessionId}?ticket=${encodeURIComponent(ticket)}`
    ws = new WebSocket(url)
    ws.onopen = () => {
      while (sendQueue.length) ws.send(sendQueue.shift())
      handlers.onOpen?.()
    }
    ws.onclose = (event) => handlers.onClose?.(event)
    ws.onerror = (event) => handlers.onError?.(event)
    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data)
      handlers.onMessage?.(msg)
    }
    if (closed) ws.close()
  })()

  return {
    send(payload) {
      // Stamp the protocol envelope here so no caller has to remember to.
      // A control frame keeps the id of the turn it acts on — a "stop" belongs
      // to the answer it interrupts, not to a turn of its own.
      const isControl = payload.mode === 'stop' || payload.type === 'stop'
      const requestId = isControl && lastRequestId ? lastRequestId : nextRequestId()
      if (!isControl) lastRequestId = requestId
      const data = JSON.stringify({
        schema_version: SCHEMA_VERSION,
        request_id: requestId,
        ...payload,   // an explicit value from the caller wins
      })
      if (ws && ws.readyState === WebSocket.OPEN) ws.send(data)
      else sendQueue.push(data)
    },
    get lastRequestId() {
      return lastRequestId
    },
    close() {
      closed = true
      ws?.close()
    },
    get raw() {
      return ws
    },
  }
}
