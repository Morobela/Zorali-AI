export function createZoraliSocket(sessionId, handlers = {}) {
  const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
  const token = localStorage.getItem('zorali_token') || ''
  const url = `${protocol}://${window.location.host}/ws/chat/${sessionId}?token=${encodeURIComponent(token)}`
  const ws = new WebSocket(url)
  ws.onopen = () => handlers.onOpen?.()
  ws.onclose = (event) => handlers.onClose?.(event)
  ws.onerror = (event) => handlers.onError?.(event)
  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data)
    handlers.onMessage?.(msg)
  }
  return {
    send(payload) { ws.send(JSON.stringify(payload)) },
    close() { ws.close() },
    raw: ws,
  }
}
