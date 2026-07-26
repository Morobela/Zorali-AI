"""Per-scope inference cost attribution (capability map U7).

``energy_scorer`` already prices every provider call, but the number went
only into a global sliding window — nothing could say *which* piece of work
spent it. This adds a context-scoped meter: open one around a unit of work,
and every provider call made inside it adds to that meter's total.

``contextvars`` is what makes this correct under concurrency. Each asyncio
task gets a copy of the context at creation, so two goal steps running in
parallel (U2 submits them to the task queue as separate tasks) each see
their own meter and cannot contaminate each other's total.

Outside a meter, ``record_cost`` is a no-op — ordinary chat turns pay no
bookkeeping cost and behave exactly as before.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field


@dataclass
class CostMeter:
    """Accumulator for one scope of work."""

    total_usd: float = 0.0
    calls: int = 0
    # Per-provider breakdown, useful when explaining a pause.
    by_provider: dict[str, float] = field(default_factory=dict)

    def add(self, usd: float, provider: str = "unknown") -> None:
        if usd <= 0:
            # Local inference is free; still count the call so "0 spend over
            # 12 calls" is distinguishable from "no calls happened".
            self.calls += 1
            self.by_provider.setdefault(provider, 0.0)
            return
        self.total_usd += usd
        self.calls += 1
        self.by_provider[provider] = self.by_provider.get(provider, 0.0) + usd


# A stack, not a single meter: scopes nest (the task queue meters a whole
# task, the goal engine meters each step inside it), and a call must count
# towards every scope containing it — otherwise an inner meter would shadow
# the outer one and the outer total would read zero.
_active: ContextVar[tuple[CostMeter, ...]] = ContextVar("zorali_cost_meters", default=())

# Sentinel for "no ceiling", used by budget-carrying callers.
UNCAPPED = float("inf")


@contextmanager
def cost_meter():
    """Measure the inference cost of everything done inside this scope."""
    meter = CostMeter()
    token = _active.set(_active.get() + (meter,))
    try:
        yield meter
    finally:
        _active.reset(token)


def record_cost(usd: float, provider: str = "unknown") -> None:
    """Attribute one provider call's cost to every enclosing meter."""
    for meter in _active.get():
        meter.add(usd, provider)


def current_meter() -> CostMeter | None:
    """The innermost active meter, if any."""
    meters = _active.get()
    return meters[-1] if meters else None
