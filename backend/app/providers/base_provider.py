from __future__ import annotations
from abc import ABC, abstractmethod
from typing import AsyncIterator


class BaseProvider(ABC):
    name: str = "base"

    @abstractmethod
    async def stream_chat(self, messages: list[dict], model: str | None = None) -> AsyncIterator[str]:
        ...

    @abstractmethod
    async def health(self) -> dict:
        ...
