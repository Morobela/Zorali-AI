# API

- GET /api/health
- GET /api/project/status?path=/workspace
- POST /api/ws-ticket (authenticated; returns a single-use WebSocket ticket)
- WS /ws/chat/{session_id}?ticket=<ticket>
- WS /mcp?ticket=<ticket>
- GET /a2a/.well-known/agent.json

WebSockets authenticate with single-use tickets from `POST /api/ws-ticket`
(Redis-backed, 60s TTL, consumed on first connect). JWTs are never accepted
in WebSocket URLs. See README "Security notes".
