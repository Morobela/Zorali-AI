"""
Modular installable skill system.
Combines:
- OpenJarvis skill manifest + SkillTool bridge pattern
- LangChain BaseTool with dual sync/async execution
- HuggingFace PipelineRegistry for task extensibility
- LangChain Runnable protocol: invoke / batch / stream

Skills extend Zorali AI's capabilities without touching core code.
"""
from __future__ import annotations
import asyncio
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator
from pydantic import BaseModel


class SkillManifest(BaseModel):
    """Declarative metadata for a skill — loadable from YAML/TOML/Python."""
    name: str
    version: str = "0.1.0"
    description: str
    author: str = "local"
    tags: list[str] = []
    dependencies: list[str] = []  # names of other skills this requires
    input_schema: dict[str, Any] = {}
    output_schema: dict[str, Any] = {}
    enabled: bool = True


class BaseSkill(ABC):
    """
    Base class for all Zorali skills.
    Runnable protocol: every skill supports invoke (sync wrap),
    ainvoke (async), and astream (streaming output).
    Mirrors LangChain's BaseTool + HuggingFace Pipeline pattern.
    """

    manifest: SkillManifest

    @abstractmethod
    async def ainvoke(self, inputs: dict[str, Any]) -> dict[str, Any]:
        """Core async execution — all skills must implement this."""
        ...

    def invoke(self, inputs: dict[str, Any]) -> dict[str, Any]:
        """Sync wrapper — delegates to ainvoke via a new event loop if needed."""
        try:
            loop = asyncio.get_running_loop()
            # We're inside an async context; caller should use ainvoke
            raise RuntimeError("Use ainvoke() inside async contexts")
        except RuntimeError as exc:
            if "Use ainvoke" in str(exc):
                raise
            return asyncio.run(self.ainvoke(inputs))

    async def astream(self, inputs: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        """Default streaming: yield the full result as one chunk."""
        result = await self.ainvoke(inputs)
        yield result

    async def abatch(self, inputs_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Parallel batch execution — all inputs run concurrently."""
        return list(await asyncio.gather(*[self.ainvoke(inp) for inp in inputs_list]))

    def __or__(self, other: "BaseSkill") -> "SkillChain":
        """Pipe operator: skill_a | skill_b creates a sequential chain."""
        return SkillChain([self, other])

    def __repr__(self) -> str:
        return f"<Skill:{self.manifest.name} v{self.manifest.version}>"


class SkillChain(BaseSkill):
    """
    Sequential skill chain built with the pipe operator.
    Output of each skill feeds as input to the next.
    Mirrors LangChain's RunnableSequence composition pattern.
    """

    def __init__(self, steps: list[BaseSkill]):
        self.steps = steps
        self.manifest = SkillManifest(
            name=" | ".join(s.manifest.name for s in steps),
            description="Sequential chain of skills",
        )

    async def ainvoke(self, inputs: dict[str, Any]) -> dict[str, Any]:
        current = inputs
        for step in self.steps:
            current = await step.ainvoke(current)
        return current
