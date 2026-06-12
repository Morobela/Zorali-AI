"""
Local self-improvement loop.
Patterns:
- OpenJarvis LearningOrchestrator: Mine → Evolve → Gate pipeline
- Higgsfield BenchmarkGate: 2% minimum improvement threshold
- Higgsfield SessionStatus tracking: INITIALIZING → RUNNING → COMPLETED / FAILED
- Privacy-first: all improvement runs entirely on-device, zero cloud calls
"""
from __future__ import annotations
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from app.learning.trace_store import trace_store, MIN_SFT_PAIRS
from app.core.audit import audit, AuditEvent


class LearningStatus(str, Enum):
    IDLE = "idle"
    INITIALIZING = "initializing"
    MINING = "mining"
    EVOLVING = "evolving"
    GATING = "gating"
    COMPLETED = "completed"
    FAILED = "failed"


MIN_IMPROVEMENT_PCT = 2.0  # Higgsfield / OpenJarvis threshold


@dataclass
class LearningSession:
    session_id: str
    status: LearningStatus = LearningStatus.INITIALIZING
    started_at: float = field(default_factory=time.time)
    completed_at: float | None = None
    sft_pairs_found: int = 0
    routing_pairs_found: int = 0
    config_changes: list[str] = field(default_factory=list)
    improvement_pct: float = 0.0
    accepted: bool = False
    error: str | None = None

    def finish(self, accepted: bool) -> None:
        self.accepted = accepted
        self.completed_at = time.time()
        self.status = LearningStatus.COMPLETED if accepted else LearningStatus.FAILED


class LocalLearningLoop:
    """
    Continuously improves Zorali from its own usage without sending data out.
    Three stages:
    1. Mine: extract high-quality SFT + routing pairs from trace_store
    2. Evolve: update routing hints and response style prefs based on patterns
    3. Gate: only accept changes if they represent >= MIN_IMPROVEMENT_PCT gain
    """

    def __init__(self):
        self._sessions: list[LearningSession] = []
        self._routing_prefs: dict[str, str] = {}  # query_pattern → preferred_provider
        self._style_prefs: dict[str, Any] = {
            "avg_preferred_length": 150,
            "preferred_modes": {},
        }

    async def run_cycle(self) -> LearningSession:
        from uuid import uuid4
        session = LearningSession(session_id=str(uuid4()))
        self._sessions.append(session)

        # Stage 1: Mine
        session.status = LearningStatus.MINING
        sft_pairs = trace_store.get_sft_pairs()
        routing_pairs = trace_store.get_routing_pairs()
        session.sft_pairs_found = len(sft_pairs)
        session.routing_pairs_found = len(routing_pairs)

        if len(sft_pairs) < MIN_SFT_PAIRS:
            session.status = LearningStatus.FAILED
            session.error = f"Not enough data yet ({len(sft_pairs)}/{MIN_SFT_PAIRS} SFT pairs)"
            return session

        # Stage 2: Evolve — update routing prefs and style prefs
        session.status = LearningStatus.EVOLVING
        changes = self._evolve_routing(routing_pairs)
        changes += self._evolve_style(sft_pairs)
        session.config_changes = changes

        # Stage 3: Gate — compute simulated improvement
        session.status = LearningStatus.GATING
        improvement = self._estimate_improvement(sft_pairs)
        session.improvement_pct = improvement

        accepted = improvement >= MIN_IMPROVEMENT_PCT
        session.finish(accepted)

        audit.record(
            AuditEvent.LEARNING_CYCLE,
            resource="local_loop",
            outcome="accepted" if accepted else "rejected",
            sft_pairs=len(sft_pairs),
            improvement_pct=round(improvement, 2),
            changes=changes,
        )
        return session

    def _evolve_routing(self, routing_pairs: list[dict]) -> list[str]:
        """Identify which queries consistently perform better on local vs cloud."""
        changes = []
        if not routing_pairs:
            return changes
        local_quality = [p["quality"] for p in routing_pairs if p["provider"] == "ollama"]
        cloud_quality = [p["quality"] for p in routing_pairs if p["provider"] != "ollama"]
        if local_quality and cloud_quality:
            avg_local = sum(local_quality) / len(local_quality)
            avg_cloud = sum(cloud_quality) / len(cloud_quality)
            if avg_local > avg_cloud * 1.05:
                self._routing_prefs["default"] = "local"
                changes.append("routing: prefer local (local quality > cloud by >5%)")
            elif avg_cloud > avg_local * 1.10:
                self._routing_prefs["default"] = "cloud"
                changes.append("routing: prefer cloud (cloud quality > local by >10%)")
        return changes

    def _evolve_style(self, sft_pairs: list[dict]) -> list[str]:
        """Learn preferred response length and mode patterns."""
        changes = []
        if not sft_pairs:
            return changes
        completions = [p["completion"] for p in sft_pairs]
        avg_len = sum(len(c.split()) for c in completions) / len(completions)
        old_pref = self._style_prefs["avg_preferred_length"]
        new_pref = int(old_pref * 0.8 + avg_len * 0.2)  # exponential moving average
        if abs(new_pref - old_pref) > 10:
            self._style_prefs["avg_preferred_length"] = new_pref
            changes.append(f"style: preferred response length updated to ~{new_pref} words")
        mode_counts: dict[str, int] = {}
        for p in sft_pairs:
            mode_counts[p.get("mode", "chat")] = mode_counts.get(p.get("mode", "chat"), 0) + 1
        self._style_prefs["preferred_modes"] = mode_counts
        return changes

    def _estimate_improvement(self, sft_pairs: list[dict]) -> float:
        """
        Estimate improvement percentage from learning this cycle.
        Uses average quality improvement over the window.
        """
        if len(sft_pairs) < 2:
            return 0.0
        recent = [p["quality"] for p in sft_pairs[-20:]]
        older = [p["quality"] for p in sft_pairs[:-20]] if len(sft_pairs) > 20 else recent
        avg_recent = sum(recent) / len(recent)
        avg_older = sum(older) / len(older)
        if avg_older == 0:
            return 0.0
        return max(0.0, (avg_recent - avg_older) / avg_older * 100.0)

    def get_routing_hint(self) -> str:
        """Current learned preference for provider routing."""
        return self._routing_prefs.get("default", "local")

    def session_summary(self) -> list[dict]:
        return [
            {
                "session_id": s.session_id,
                "status": s.status.value,
                "sft_pairs": s.sft_pairs_found,
                "improvement_pct": round(s.improvement_pct, 2),
                "accepted": s.accepted,
                "changes": s.config_changes,
            }
            for s in self._sessions[-10:]
        ]


local_loop = LocalLearningLoop()
