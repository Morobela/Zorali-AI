export function createCharlieSocket(sessionId, handlers = {}) {
  const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
  const url = `${protocol}://${window.location.host}/ws/chat/${sessionId}`
  const ws = new WebSocket(url)
  ws.onopen = () => handlers.onOpen?.()
  ws.onclose = () => handlers.onClose?.()
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
