"""
Async continuous batching for concurrent inference requests.
Inspired by vLLM's fan-out multiplexing pattern:
- Each request gets its own async output queue
- Background dispatcher loop pulls from a shared input queue
- Chunked streaming yields control back to event loop between chunks
- InputStreamError isolates failures per-request, not globally
"""
from __future__ import annotations
import asyncio
import time
from dataclasses import dataclass, field
from typing import AsyncIterator
from uuid import uuid4


STREAM_FINISHED = object()  # sentinel — pattern from vLLM


@dataclass
class InferenceRequest:
    request_id: str = field(default_factory=lambda: str(uuid4()))
    messages: list[dict] = field(default_factory=list)
    model: str | None = None
    local_first: bool = True
    priority: int = 1  # lower = higher priority
    submitted_at: float = field(default_factory=time.monotonic)
    output_queue: asyncio.Queue = field(default_factory=asyncio.Queue)


class InputStreamError(Exception):
    """Isolates per-request failures from the shared dispatcher."""
    def __init__(self, request_id: str, cause: Exception):
        self.request_id = request_id
        self.cause = cause
        super().__init__(f"Request {request_id} failed: {cause}")


class BatchProcessor:
    """
    Continuous batching processor.
    Requests enter a priority queue; a single dispatcher
    processes them concurrently (up to max_concurrent).
    """

    def __init__(self, max_concurrent: int = 8):
        self._max_concurrent = max_concurrent
        self._input_queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._active: dict[str, InferenceRequest] = {}
        self._running = False
        self._dispatcher_task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._dispatcher_task = asyncio.create_task(self._dispatch_loop())

    async def stop(self) -> None:
        self._running = False
        if self._dispatcher_task:
            self._dispatcher_task.cancel()

    async def submit(self, request: InferenceRequest) -> str:
        await self._input_queue.put((request.priority, request.submitted_at, request))
        return request.request_id

    async def stream(self, request: InferenceRequest) -> AsyncIterator[str]:
        """Submit and stream output tokens as they arrive."""
        await self.submit(request)
        while True:
            item = await request.output_queue.get()
            if item is STREAM_FINISHED:
                break
            if isinstance(item, InputStreamError):
                raise item.cause
            yield item
            # Yield control to event loop between chunks (vLLM pattern)
            await asyncio.sleep(0)

    async def _dispatch_loop(self) -> None:
        """Background loop: drain input queue, dispatch to provider."""
        while self._running:
            try:
                _, _, request = await asyncio.wait_for(
                    self._input_queue.get(), timeout=1.0
                )
                if len(self._active) < self._max_concurrent:
                    self._active[request.request_id] = request
                    asyncio.create_task(self._process(request))
                else:
                    # Backpressure: re-queue
                    await self._input_queue.put(
                        (request.priority, request.submitted_at, request)
                    )
                    await asyncio.sleep(0.05)
            except asyncio.TimeoutError:
                continue
            except Exception:
                continue

    async def _process(self, request: InferenceRequest) -> None:
        from app.providers.provider_router import router as provider_router
        try:
            async for token, _ in provider_router.stream_chat(
                request.messages, model=request.model, local_first=request.local_first
            ):
                await request.output_queue.put(token)
        except Exception as exc:
            await request.output_queue.put(InputStreamError(request.request_id, exc))
        finally:
            await request.output_queue.put(STREAM_FINISHED)
            self._active.pop(request.request_id, None)

    def stats(self) -> dict:
        return {
            "queued": self._input_queue.qsize(),
            "active": len(self._active),
            "max_concurrent": self._max_concurrent,
        }


batch_processor = BatchProcessor()
