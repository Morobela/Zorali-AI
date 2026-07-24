# API

- GET /api/health
- GET /api/project/status?path=/workspace
- POST /api/ws-ticket (authenticated; returns a single-use WebSocket ticket)
- WS /ws/chat/{session_id}?ticket=<ticket>
- WS /mcp?ticket=<ticket>
- GET /a2a/.well-known/agent.json
- POST /a2a/tasks/send (authenticated; runs the task through the agent orchestrator in the background — poll the task for the result)
- GET /a2a/tasks/{task_id} (authenticated, owner-scoped; status: submitted → running → completed/failed)
- GET /a2a/tasks (authenticated, owner-scoped)

WebSockets authenticate with single-use tickets from `POST /api/ws-ticket`
(Redis-backed, 60s TTL, consumed on first connect). JWTs are never accepted
in WebSocket URLs. See README "Security notes".
