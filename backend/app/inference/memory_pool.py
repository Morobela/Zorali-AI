"""
Block-pooled request memory manager.
Inspired by vLLM's PagedAttention: decouple logical request slots
from physical memory pages to eliminate fragmentation and allow
multiple concurrent users without wasting memory.

This Python implementation manages prompt/context buffers, not GPU KV-cache,
but applies the same paged-allocation principle at the application layer.
"""
from __future__ import annotations
import uuid
from dataclasses import dataclass, field
from collections import deque


BLOCK_SIZE = 512  # tokens per block (configurable)
MAX_BLOCKS = 256  # hard cap on concurrent blocks


@dataclass
class MemoryBlock:
    block_id: str
    capacity: int
    content: list[dict] = field(default_factory=list)
    ref_count: int = 0

    @property
    def is_free(self) -> bool:
        return self.ref_count == 0

    def acquire(self) -> None:
        self.ref_count += 1

    def release(self) -> None:
        self.ref_count = max(0, self.ref_count - 1)
        if self.ref_count == 0:
            self.content.clear()


@dataclass
class LogicalSlot:
    """Maps one request to a list of physical blocks."""
    slot_id: str
    blocks: list[str] = field(default_factory=list)  # block IDs

    def total_tokens(self, pool: "MemoryPool") -> int:
        return sum(len(pool._blocks[b].content) for b in self.blocks if b in pool._blocks)


class MemoryPool:
    """
    Fixed-size pool of reusable memory blocks.
    Requests lease blocks, return them on completion.
    Prevents any single request from exhausting all memory.
    """

    def __init__(self, max_blocks: int = MAX_BLOCKS, block_size: int = BLOCK_SIZE):
        self._max_blocks = max_blocks
        self._block_size = block_size
        self._blocks: dict[str, MemoryBlock] = {}
        self._free_queue: deque[str] = deque()
        self._slots: dict[str, LogicalSlot] = {}
        self._initialize_pool()

    def _initialize_pool(self) -> None:
        for _ in range(self._max_blocks):
            bid = str(uuid.uuid4())
            self._blocks[bid] = MemoryBlock(block_id=bid, capacity=self._block_size)
            self._free_queue.append(bid)

    def _allocate_block(self) -> str | None:
        """Grab a free block from the pool. Returns None if pool exhausted."""
        while self._free_queue:
            bid = self._free_queue.popleft()
            if self._blocks[bid].is_free:
                return bid
        return None

    def acquire_slot(self, initial_messages: list[dict] | None = None) -> str:
        """
        Reserve a logical slot (request context) backed by one or more blocks.
        Returns slot_id. Raises RuntimeError if pool is exhausted.
        """
        bid = self._allocate_block()
        if bid is None:
            raise RuntimeError("Memory pool exhausted — too many concurrent requests")
        self._blocks[bid].acquire()
        slot_id = str(uuid.uuid4())
        slot = LogicalSlot(slot_id=slot_id, blocks=[bid])
        self._slots[slot_id] = slot
        if initial_messages:
            self.extend_slot(slot_id, initial_messages)
        return slot_id

    def extend_slot(self, slot_id: str, messages: list[dict]) -> None:
        """Append messages to a slot, allocating new blocks as needed."""
        slot = self._slots.get(slot_id)
        if not slot:
            raise KeyError(f"Unknown slot: {slot_id}")
        for msg in messages:
            current_block = self._blocks[slot.blocks[-1]]
            if len(current_block.content) >= current_block.capacity:
                bid = self._allocate_block()
                if bid is None:
                    raise RuntimeError("Memory pool exhausted during slot extension")
                self._blocks[bid].acquire()
                slot.blocks.append(bid)
                current_block = self._blocks[bid]
            current_block.content.append(msg)

    def read_slot(self, slot_id: str) -> list[dict]:
        """Read all messages stored in a slot across all its blocks."""
        slot = self._slots.get(slot_id)
        if not slot:
            return []
        result = []
        for bid in slot.blocks:
            result.extend(self._blocks[bid].content)
        return result

    def release_slot(self, slot_id: str) -> None:
        """Return all blocks belonging to this slot back to the pool."""
        slot = self._slots.pop(slot_id, None)
        if not slot:
            return
        for bid in slot.blocks:
            blk = self._blocks.get(bid)
            if blk:
                blk.release()
                if blk.is_free:
                    self._free_queue.append(bid)

    def stats(self) -> dict:
        free = len(self._free_queue)
        used = self._max_blocks - free
        return {
            "total_blocks": self._max_blocks,
            "free_blocks": free,
            "used_blocks": used,
            "active_slots": len(self._slots),
            "utilization_pct": round(used / self._max_blocks * 100, 1),
        }


# Singleton pool shared across all concurrent requests
memory_pool = MemoryPool()
