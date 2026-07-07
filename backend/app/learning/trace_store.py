"""
Usage trace collector for the local learning loop.
Pattern: OpenJarvis TraceStore — background collection of all agent
execution traces during normal operation. Data stays on-device.
Privacy-first: no trace data is ever sent to the cloud.
"""
from __future__ import annotations
import json
import os
import time
from pathlib import Path
from dataclasses import dataclass, asdict, field
from typing import Any
from collections import deque

# Honour ZORALI_DATA_DIR env var so CI runners and non-Docker environments work
_DATA_DIR = Path(os.environ.get("ZORALI_DATA_DIR", "/app/data"))
TRACES_FILE = _DATA_DIR / "traces.jsonl"
MAX_IN_MEMORY = 1000
MIN_SFT_PAIRS = 10  # OpenJarvis minimum before triggering training


@dataclass
class Trace:
    trace_id: str
    session_id: str
    user_message: str
    assistant_response: str
    mode: str
    provider: str
    latency_ms: float
    tokens: int
    rating: float | None  # user feedback 0-1, None if not rated
    ts: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def quality_score(self) -> float:
        """
        Estimate trace quality without user feedback.
        Uses response length as proxy (too short = bad, too long = verbose).
        """
        if self.rating is not None:
            return self.rating
        ideal_tokens = 150
        length_score = min(1.0, self.tokens / ideal_tokens) if self.tokens < ideal_tokens else max(0.3, 1.0 - (self.tokens - ideal_tokens) / 1000)
        latency_score = max(0.0, 1.0 - self.latency_ms / 30000)
        return (length_score * 0.6 + latency_score * 0.4)


class TraceStore:
    """
    Append-only trace store backed by JSONL on disk.
    In-memory deque for fast recent access.
    All data stays local — privacy-first design.
    """

    def __init__(self, path: Path = TRACES_FILE):
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._recent: deque[Trace] = deque(maxlen=MAX_IN_MEMORY)
        self._load_recent()

    def _load_recent(self) -> None:
        if not self._path.exists():
            return
        try:
            lines = self._path.read_text().strip().splitlines()
            for line in lines[-MAX_IN_MEMORY:]:
                try:
                    d = json.loads(line)
                    self._recent.append(Trace(**d))
                except Exception:
                    continue
        except Exception:
            pass

    def record(self, trace: Trace) -> None:
        self._recent.append(trace)
        try:
            with self._path.open("a") as f:
                f.write(json.dumps(asdict(trace)) + "\n")
        except Exception:
            pass

    def get_sft_pairs(self, min_quality: float = 0.6) -> list[dict]:
        """
        Extract supervised fine-tuning pairs from high-quality traces.
        Pattern: OpenJarvis TrainingDataMiner — quality threshold gating.
        """
        pairs = []
        for t in self._recent:
            if t.quality_score() >= min_quality and t.user_message and t.assistant_response:
                pairs.append({
                    "prompt": t.user_message,
                    "completion": t.assistant_response,
                    "quality": t.quality_score(),
                    "mode": t.mode,
                })
        return pairs

    def get_routing_pairs(self) -> list[dict]:
        """
        Extract provider routing training pairs.
        Useful for learning which queries work better on local vs cloud.
        """
        pairs = []
        for t in self._recent:
            if t.latency_ms > 0:
                pairs.append({
                    "message": t.user_message,
                    "provider": t.provider,
                    "latency_ms": t.latency_ms,
                    "quality": t.quality_score(),
                })
        return pairs

    def stats(self) -> dict:
        total = len(self._recent)
        sft = self.get_sft_pairs()
        return {
            "total_traces": total,
            "high_quality_traces": len(sft),
            "ready_for_training": len(sft) >= MIN_SFT_PAIRS,
            "min_sft_threshold": MIN_SFT_PAIRS,
        }


trace_store = TraceStore()
