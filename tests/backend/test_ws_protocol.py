"""The chat WebSocket contract (docs/CODE_ANALYSIS.md recommendations 1 and 2).

The protocol was untyped for long enough to grow a second frame producer
without anyone registering it as one. These tests pin the three things that
were missing: a validated inbound frame, a closed set of outbound frames, and
an envelope every frame carries.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.api.ws_protocol import (
    INBOUND_MODES,
    OUTBOUND_TYPES,
    SCHEMA_VERSION,
    ErrorCode,
    FrameEmitter,
    parse_inbound,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
# Every module that writes frames onto the chat socket.
EMITTING_MODULES = (
    "backend/app/api/chat.py",
    "backend/app/agents/goal_engine.py",
    "backend/app/agents/chat_tools.py",
)


class Recorder:
    """Stands in for websocket.send_json."""

    def __init__(self) -> None:
        self.frames: list[dict] = []

    async def __call__(self, frame: dict) -> None:
        self.frames.append(frame)


# ── inbound validation ───────────────────────────────────────────────────────

def test_a_minimal_frame_gets_every_default() -> None:
    frame, problem = parse_inbound({"message": "hello"})

    assert problem is None
    assert frame.mode == "chat"
    assert frame.project_id == "default"
    assert frame.local_first is True
    assert frame.tools_enabled is True
    assert frame.request_id  # generated when the client omits one


def test_a_client_supplied_request_id_is_kept() -> None:
    frame, _ = parse_inbound({"message": "hi", "request_id": "abc-123"})

    assert frame.request_id == "abc-123"


@pytest.mark.parametrize("mode", sorted(INBOUND_MODES))
def test_every_documented_mode_is_accepted(mode: str) -> None:
    frame, problem = parse_inbound({"mode": mode, "message": "x"})

    assert problem is None
    assert frame.mode == mode


def test_an_unknown_mode_is_refused_rather_than_treated_as_chat() -> None:
    # Silently falling back to chat turns a client typo into a surprise LLM call.
    frame, problem = parse_inbound({"mode": "chatt", "message": "x"})

    assert frame is None
    assert "Unknown mode" in problem


def test_a_non_object_frame_is_refused() -> None:
    frame, problem = parse_inbound(["not", "an", "object"])

    assert frame is None
    assert problem


def test_unknown_fields_are_tolerated() -> None:
    # A client newer than this server must degrade, not fail.
    frame, problem = parse_inbound({"message": "hi", "some_future_field": 42})

    assert problem is None
    assert frame.message == "hi"


def test_both_spellings_of_stop_are_understood() -> None:
    # Older clients send {"type": "stop"}; newer ones send {"mode": "stop"}.
    by_mode, _ = parse_inbound({"mode": "stop"})
    by_type, _ = parse_inbound({"type": "stop"})

    assert by_mode.is_stop
    assert by_type.is_stop
    assert not parse_inbound({"message": "hi"})[0].is_stop


# ── outbound envelope ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_every_frame_carries_the_schema_version_and_request_id() -> None:
    recorder = Recorder()
    emitter = FrameEmitter(recorder)
    emitter.begin_turn("turn-1")

    await emitter.send({"type": "token", "content": "hi"})

    assert recorder.frames == [
        {"type": "token", "content": "hi", "schema_version": SCHEMA_VERSION, "request_id": "turn-1"}
    ]


@pytest.mark.asyncio
async def test_existing_fields_are_untouched() -> None:
    """The envelope is additive — a client reading `content` keeps working."""
    recorder = Recorder()
    emitter = FrameEmitter(recorder)
    emitter.begin_turn("t")

    await emitter.send({"type": "done", "citations": [], "stopped": False, "latency_ms": 12})

    frame = recorder.frames[0]
    assert frame["type"] == "done"
    assert frame["citations"] == []
    assert frame["stopped"] is False
    assert frame["latency_ms"] == 12


@pytest.mark.asyncio
async def test_error_frames_carry_a_machine_readable_code() -> None:
    recorder = Recorder()
    emitter = FrameEmitter(recorder)
    emitter.begin_turn(None)

    await emitter.error(ErrorCode.EMPTY_MESSAGE, "Empty message")

    frame = recorder.frames[0]
    assert frame["code"] == "empty_message"
    # `content` stays, because that is what the shipped UI renders.
    assert frame["content"] == "Empty message"


@pytest.mark.asyncio
async def test_a_frame_with_no_turn_omits_the_request_id() -> None:
    recorder = Recorder()
    emitter = FrameEmitter(recorder)
    emitter.begin_turn(None)

    await emitter.error(ErrorCode.INVALID_FRAME, "bad")

    assert "request_id" not in recorder.frames[0]


@pytest.mark.asyncio
async def test_an_undeclared_frame_type_is_refused() -> None:
    recorder = Recorder()
    emitter = FrameEmitter(recorder)

    with pytest.raises(ValueError, match="Undeclared outbound frame type"):
        await emitter.send({"type": "surprise", "content": "x"})

    assert recorder.frames == []


@pytest.mark.asyncio
async def test_the_emitter_is_callable_so_it_can_replace_send_json() -> None:
    # goal_engine and chat_tools receive it as emit= / emit_event= and keep
    # building plain dicts; the envelope is applied for them.
    recorder = Recorder()
    emitter = FrameEmitter(recorder)
    emitter.begin_turn("t")

    await emitter({"type": "goal_update", "data": {"id": "g1"}})

    assert recorder.frames[0]["schema_version"] == SCHEMA_VERSION
    assert recorder.frames[0]["request_id"] == "t"


# ── the contract cannot drift from the code ──────────────────────────────────

@pytest.mark.parametrize("relative", EMITTING_MODULES)
def test_no_module_emits_a_frame_type_the_contract_does_not_declare(relative: str) -> None:
    """The failure this whole change exists to prevent.

    `goal` mode added `goal_update` to an undocumented protocol and nothing
    noticed. Now a new frame type that is not in OUTBOUND_TYPES fails here.
    """
    source = (REPO_ROOT / relative).read_text(encoding="utf-8")
    emitted = set(re.findall(r'"type":\s*"([a-z_]+)"', source))
    # `_task_result` builds its payload with a nested "status" key; the frame
    # type itself is what matters, and every literal here is one.
    undeclared = emitted - OUTBOUND_TYPES

    assert not undeclared, (
        f"{relative} emits {sorted(undeclared)}, which ws_protocol.OUTBOUND_TYPES "
        "does not declare. Add them there and to docs/API.md."
    )


def test_the_documented_frame_types_match_the_contract() -> None:
    """docs/API.md lists the frames; the list must be the real one."""
    api_doc = (REPO_ROOT / "docs" / "API.md").read_text(encoding="utf-8")
    documented = {
        name for name in OUTBOUND_TYPES if f"`{name}`" in api_doc
    }

    assert documented == OUTBOUND_TYPES, (
        f"Undocumented frame types: {sorted(OUTBOUND_TYPES - documented)}"
    )
