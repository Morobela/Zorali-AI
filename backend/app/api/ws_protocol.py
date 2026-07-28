"""The chat WebSocket contract.

`/ws/chat/{session_id}` multiplexes every realtime interaction onto one socket,
and for a long time it did so untyped: the server dispatched on a bare ``mode``
string and three separate modules wrote frame dicts by hand. Nothing declared
what a frame looked like, so nothing could tell when the frontend and backend
drifted apart — and `goal` mode added a second frame producer to that surface
without anyone noticing it was a second producer.

This module is the declaration. It holds:

- :class:`InboundFrame` — everything a client may send, validated.
- :data:`OUTBOUND_TYPES` — the closed set of frames the server may send.
- :class:`FrameEmitter` — the only way frames leave, so every one of them
  carries ``schema_version`` and the ``request_id`` of the turn that caused it.

**Compatibility.** Version 1 is deliberately additive: every field the frontend
already reads keeps its name, position and meaning, and the new keys are extra.
An older client ignores them; a newer client may send fields this server has
never heard of and is tolerated rather than rejected. The contract can tighten
later — it cannot un-break a client that stopped working today.
"""
from __future__ import annotations

from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = 1

# Modes a client may ask for. `chat` and `task` and `goal` carry a message;
# `status` and `stop` are control frames.
INBOUND_MODES = frozenset({"chat", "task", "goal", "status", "stop"})

# Every frame the server is allowed to send. Adding one means adding it here —
# `test_ws_protocol` scans the emitting modules and fails if a literal appears
# that this set does not know about.
OUTBOUND_TYPES = frozenset({
    "token",        # one streamed chunk of a chat answer
    "done",         # end of a chat turn, with citations and timings
    "error",        # something went wrong; carries a machine-readable code
    "status",       # project scan result
    "task_result",  # slash-command result
    "goal_token",   # one streamed chunk from a goal step
    "goal_update",  # goal checklist state changed
    "tool_use",     # the model decided to call a tool
    "tool_result",  # that tool returned
})


class ErrorCode:
    """Machine-readable reasons, so a client can branch without parsing prose."""

    INVALID_FRAME = "invalid_frame"
    UNKNOWN_MODE = "unknown_mode"
    EMPTY_MESSAGE = "empty_message"
    GOAL_DISABLED = "goal_disabled"
    GOAL_FAILED = "goal_failed"
    INTERNAL_ERROR = "internal_error"


class InboundFrame(BaseModel):
    """One message from the client.

    Unknown fields are kept rather than rejected: a client newer than this
    server must degrade, not fail. Unknown *modes* are refused, because
    silently treating a typo'd mode as `chat` is how a client bug becomes a
    surprising LLM call.
    """

    model_config = ConfigDict(extra="allow", protected_namespaces=())

    mode: str = "chat"
    # Legacy alternative to mode="stop", still sent by older clients.
    type: str | None = None
    message: str = ""
    project_id: str = "default"
    model: str | None = None
    local_first: bool = True
    deep_research: bool = False
    regenerate: bool = False
    edit_last: bool = False
    tools_enabled: bool = True
    attachments: list[Any] = Field(default_factory=list)
    # Correlation id for this turn. Generated when the client omits one, and
    # echoed on every frame the turn produces.
    request_id: str = Field(default_factory=lambda: str(uuid4()))
    schema_version: int | None = None

    @property
    def is_stop(self) -> bool:
        return self.mode == "stop" or self.type == "stop"


def parse_inbound(raw: Any) -> tuple[InboundFrame | None, str | None]:
    """(frame, error). Never raises — a malformed frame is a reply, not a crash."""
    if not isinstance(raw, dict):
        return None, "A frame must be a JSON object."
    try:
        frame = InboundFrame.model_validate(raw)
    except Exception as exc:  # pydantic ValidationError, or anything odd
        return None, f"Malformed frame: {exc}"
    if frame.mode not in INBOUND_MODES:
        return None, (
            f"Unknown mode {frame.mode!r}. Expected one of: "
            + ", ".join(sorted(INBOUND_MODES))
        )
    return frame, None


class FrameEmitter:
    """Stamps and sends every outbound frame.

    Passed wherever a raw ``websocket.send_json`` used to be — including into
    the goal engine and the tool loop, which keep building plain dicts and get
    the envelope for free.
    """

    __slots__ = ("_send", "_request_id")

    def __init__(self, send) -> None:
        self._send = send
        self._request_id: str | None = None

    def begin_turn(self, request_id: str | None) -> None:
        """Frames from here on belong to this request."""
        self._request_id = request_id

    async def __call__(self, frame: dict) -> None:
        """Callable so it can be passed as ``emit=`` / ``emit_event=``."""
        await self.send(frame)

    async def send(self, frame: dict) -> None:
        kind = frame.get("type")
        if kind not in OUTBOUND_TYPES:
            # A frame type nothing declared is a bug in the sender, not
            # something to pass to a client that cannot know what it means.
            raise ValueError(
                f"Undeclared outbound frame type {kind!r}. "
                "Add it to ws_protocol.OUTBOUND_TYPES and document it in docs/API.md."
            )
        stamped = {**frame, "schema_version": SCHEMA_VERSION}
        if self._request_id is not None:
            stamped["request_id"] = self._request_id
        await self._send(stamped)

    async def error(self, code: str, message: str) -> None:
        # `content` is what every existing client reads; `code` is the addition.
        await self.send({"type": "error", "code": code, "content": message})
