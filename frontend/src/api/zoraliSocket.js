import { apiPost } from './httpClient.js'

// Opens the chat WebSocket using a single-use auth ticket. The JWT itself
// never appears in the URL (query strings end up in server access logs);
// instead we exchange it for a short-lived ticket over an authenticated POST,
// and the backend consumes that ticket on connect.
export function createZoraliSocket(sessionId, handlers = {}) {
  const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
  let ws = null
  let closed = false
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
      const data = JSON.stringify(payload)
      if (ws && ws.readyState === WebSocket.OPEN) ws.send(data)
      else sendQueue.push(data)
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
