"""Single-use WebSocket auth tickets (POST /api/ws-ticket + Redis store).

The WS handshake never sees a JWT: clients exchange their access token for a
random short-TTL ticket over an authenticated POST and the backend consumes
the ticket atomically on connect.
"""
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import app
from conftest import ws_ticket

client = TestClient(app)


def test_ws_ticket_endpoint_issues_single_use_ticket():
    resp = client.post("/api/ws-ticket")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ticket"] and len(body["ticket"]) >= 32
    assert body["expires_in"] == 60


def test_two_tickets_are_distinct():
    assert ws_ticket(client) != ws_ticket(client)


def test_ws_connect_with_valid_ticket_works():
    with client.websocket_connect(f"/ws/chat/ticket-ok?ticket={ws_ticket(client)}") as ws:
        ws.send_json({"mode": "status"})
        msg = ws.receive_json()
        assert msg["type"] == "status"


def test_ticket_is_consumed_on_first_use():
    ticket = ws_ticket(client)
    with client.websocket_connect(f"/ws/chat/first-use?ticket={ticket}") as ws:
        ws.send_json({"mode": "status"})
        assert ws.receive_json()["type"] == "status"
    # Same ticket again: already redeemed → policy violation close.
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(f"/ws/chat/replay?ticket={ticket}"):
            pass
    assert exc.value.code == 1008


def test_mcp_ws_requires_ticket():
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/mcp"):
            pass
    assert exc.value.code == 1008
    # And connects with a valid one.
    with client.websocket_connect(f"/mcp?ticket={ws_ticket(client)}") as ws:
        ws.send_json({"method": "initialize", "id": 1})
        reply = ws.receive_json()
        assert reply["result"]["serverInfo"]["name"] == "zorali-ai"
