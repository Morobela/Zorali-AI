"""
Runnable protocol — universal chainable interface.
Patterns:
- LangChain Runnable[Input, Output]: generic typed base for all chainable components
- LangChain: operator overloading (|) for pipe composition
- LangChain: three execution modes (invoke / batch / stream) with async variants
- LangChain: RunnableConfig for implicit context propagation
- LangChain: layered error management (retry / fallback wrappers)
"""
from __future__ import annotations
import asyncio
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Generic, TypeVar
from dataclasses import dataclass, field

Input = TypeVar("Input")
Output = TypeVar("Output")


@dataclass
class RunnableConfig:
    """
    Propagates execution context through a chain without explicit parameter passing.
    Pattern: LangChain RunnableConfig threading.
    """
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    max_retries: int = 0
    callbacks: list[Any] = field(default_factory=list)


class Runnable(ABC, Generic[Input, Output]):
    """
    Base runnable. Every component that participates in a chain inherits this.
    Provides: invoke, ainvoke, batch, abatch, stream, astream.
    """

    @abstractmethod
    async def ainvoke(self, inputs: Input, config: RunnableConfig | None = None) -> Output:
        ...

    def invoke(self, inputs: Input, config: RunnableConfig | None = None) -> Output:
        try:
            asyncio.get_running_loop()  # probe: raises RuntimeError when no loop
            raise RuntimeError("Use ainvoke() inside async contexts")
        except RuntimeError as exc:
            if "Use ainvoke" in str(exc):
                raise
            return asyncio.run(self.ainvoke(inputs, config))

    async def abatch(
        self, inputs_list: list[Input], config: RunnableConfig | None = None
    ) -> list[Output]:
        return list(await asyncio.gather(*[self.ainvoke(inp, config) for inp in inputs_list]))

    async def astream(
        self, inputs: Input, config: RunnableConfig | None = None
    ) -> AsyncIterator[Output]:
        result = await self.ainvoke(inputs, config)
        yield result

    async def with_retry(self, inputs: Input, config: RunnableConfig | None = None, retries: int = 3) -> Output:
        cfg = config or RunnableConfig(max_retries=retries)
        last_exc = None
        for attempt in range(retries + 1):
            try:
                return await self.ainvoke(inputs, cfg)
            except Exception as exc:
                last_exc = exc
                if attempt < retries:
                    await asyncio.sleep(2 ** attempt)
        raise last_exc

    def __or__(self, other: "Runnable") -> "RunnableSequence":
        return RunnableSequence([self, other])

    def __ror__(self, other: "Runnable") -> "RunnableSequence":
        return RunnableSequence([other, self])


class RunnableSequence(Runnable):
    """
    Sequential chain: output of step N feeds into step N+1.
    Pattern: LangChain RunnableSequence.
    """

    def __init__(self, steps: list[Runnable]):
        self.steps = steps

    async def ainvoke(self, inputs: Any, config: RunnableConfig | None = None) -> Any:
        current = inputs
        for step in self.steps:
            current = await step.ainvoke(current, config)
        return current

    async def astream(self, inputs: Any, config: RunnableConfig | None = None) -> AsyncIterator[Any]:
        current = inputs
        for i, step in enumerate(self.steps[:-1]):
            current = await step.ainvoke(current, config)
        async for chunk in self.steps[-1].astream(current, config):
            yield chunk

    def __or__(self, other: Runnable) -> "RunnableSequence":
        return RunnableSequence(self.steps + [other])


class RunnableParallel(Runnable):
    """
    Runs multiple runnables concurrently on the same input and merges results.
    Pattern: LangChain inline dict composition for parallel execution.
    """

    def __init__(self, branches: dict[str, Runnable]):
        self.branches = branches

    async def ainvoke(self, inputs: Any, config: RunnableConfig | None = None) -> dict[str, Any]:
        results = await asyncio.gather(*[r.ainvoke(inputs, config) for r in self.branches.values()])
        return dict(zip(self.branches.keys(), results))


class RunnableLambda(Runnable):
    """Wrap a plain async function as a Runnable."""

    def __init__(self, fn):
        self._fn = fn

    async def ainvoke(self, inputs: Any, config: RunnableConfig | None = None) -> Any:
        return await self._fn(inputs)
