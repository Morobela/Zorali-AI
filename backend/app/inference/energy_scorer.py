"""
Energy and cost-aware inference scoring.
Inspired by OpenJarvis: FLOPs, latency, and dollar cost are
first-class constraints, not afterthoughts.

Measures every inference call and exposes a cost signal so the
provider router can make informed local-vs-cloud decisions.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from collections import deque
from typing import Deque

# Provider cost table (USD per 1K tokens). Extend as needed.
# Pattern: OpenJarvis PRICING lookup table.
PRICING_TABLE: dict[str, tuple[float, float]] = {
    "ollama": (0.0, 0.0),           # local — no cost
    "openai/gpt-4o-mini": (0.00015, 0.00060),
    "openai/gpt-4o": (0.005, 0.015),
    "openai/gpt-4": (0.03, 0.06),
    "anthropic/claude-haiku": (0.00025, 0.00125),
    "anthropic/claude-sonnet": (0.003, 0.015),
    "none": (0.0, 0.0),
}


@dataclass
class InferenceScore:
    provider: str
    model: str
    latency_ms: float
    input_tokens: int
    output_tokens: int
    estimated_flops: float
    cost_usd: float
    efficiency_score: float  # higher = more efficient


@dataclass
class _Window:
    scores: Deque[InferenceScore] = field(default_factory=lambda: deque(maxlen=200))

    def add(self, score: InferenceScore) -> None:
        self.scores.append(score)

    def avg_latency_ms(self) -> float:
        if not self.scores:
            return 0.0
        return sum(s.latency_ms for s in self.scores) / len(self.scores)

    def total_cost_usd(self) -> float:
        return sum(s.cost_usd for s in self.scores)

    def avg_efficiency(self) -> float:
        if not self.scores:
            return 0.0
        return sum(s.efficiency_score for s in self.scores) / len(self.scores)


class EnergyScorer:
    """
    Wraps an inference call and records energy/cost metrics.
    Uses a sliding window (last 200 calls) for live efficiency stats.
    """

    def __init__(self):
        self._window = _Window()

    def _estimate_flops(self, tokens: int, model: str) -> float:
        """
        Rough FLOP estimate: each output token ≈ 2 × parameter_count MACs.
        Parameter counts are conservative estimates for common model families.
        """
        param_map = {
            "1b": 1e9, "3b": 3e9, "7b": 7e9, "8b": 8e9,
            "13b": 13e9, "14b": 14e9, "70b": 70e9,
            "gpt-4o-mini": 8e9, "gpt-4o": 200e9, "gpt-4": 1e12,
            "claude-haiku": 20e9, "claude-sonnet": 70e9,
        }
        params = 7e9  # default assumption
        model_lower = model.lower()
        for key, val in param_map.items():
            if key in model_lower:
                params = val
                break
        return 2.0 * params * tokens

    def _cost_usd(self, provider: str, model: str, input_tok: int, output_tok: int) -> float:
        key = f"{provider}/{model}".lower()
        rates = PRICING_TABLE.get(key) or PRICING_TABLE.get(provider.lower(), (0.0, 0.0))
        return (input_tok * rates[0] + output_tok * rates[1]) / 1000.0

    def _efficiency_score(self, latency_ms: float, cost_usd: float, output_tokens: int) -> float:
        """
        Efficiency = output quality per unit cost and time.
        Formula: tokens / (1 + latency_s) / (1 + cost_usd * 1000)
        Score is relative — higher is better.
        """
        if output_tokens == 0:
            return 0.0
        latency_s = latency_ms / 1000.0
        return output_tokens / ((1.0 + latency_s) * (1.0 + cost_usd * 1000.0))

    def score(
        self,
        provider: str,
        model: str,
        latency_ms: float,
        input_tokens: int,
        output_tokens: int,
    ) -> InferenceScore:
        flops = self._estimate_flops(output_tokens, model)
        cost = self._cost_usd(provider, model, input_tokens, output_tokens)
        eff = self._efficiency_score(latency_ms, cost, output_tokens)
        s = InferenceScore(
            provider=provider,
            model=model,
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_flops=flops,
            cost_usd=cost,
            efficiency_score=eff,
        )
        self._window.add(s)
        return s

    def stats(self) -> dict:
        return {
            "window_size": len(self._window.scores),
            "avg_latency_ms": round(self._window.avg_latency_ms(), 2),
            "total_cost_usd": round(self._window.total_cost_usd(), 6),
            "avg_efficiency": round(self._window.avg_efficiency(), 4),
        }

    def should_prefer_local(self, budget_usd_remaining: float = 1.0) -> bool:
        """
        Cost-aware routing hint: prefer local if budget is tight
        or local has been serving requests efficiently.
        Pattern: OpenJarvis selective cloud offloading logic.
        """
        stats = self.stats()
        if budget_usd_remaining <= 0.01:
            return True
        if stats["window_size"] > 10 and stats["avg_efficiency"] > 5.0:
            return True  # local is working well
        return False


energy_scorer = EnergyScorer()
