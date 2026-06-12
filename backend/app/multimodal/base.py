"""
Multi-modal inference pipeline base.
Patterns:
- HuggingFace Transformers Pipeline: preprocess → _forward → postprocess
- HuggingFace: modality-agnostic abstract class with optional component composition
- HuggingFace ChunkPipeline: chunked processing for long documents
- LangChain Runnable: consistent invoke/stream interface
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator
from dataclasses import dataclass


@dataclass
class ModalityInput:
    modality: str          # "text" | "image" | "audio" | "video"
    content: Any           # str, bytes, or URL
    mime_type: str = ""
    metadata: dict = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


@dataclass
class ModalityOutput:
    modality: str
    content: Any
    confidence: float = 1.0
    metadata: dict = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class BaseModalPipeline(ABC):
    """
    Abstract multi-modal pipeline.
    Three-stage processing: preprocess → forward → postprocess.
    Subclasses implement each stage; base class orchestrates the flow.
    """

    name: str = "base"
    supported_modalities: list[str] = []

    @abstractmethod
    async def preprocess(self, inputs: ModalityInput) -> dict[str, Any]:
        """Convert raw input into model-ready tensors/embeddings."""
        ...

    @abstractmethod
    async def _forward(self, preprocessed: dict[str, Any]) -> dict[str, Any]:
        """Run the actual inference/processing."""
        ...

    @abstractmethod
    async def postprocess(self, raw_output: dict[str, Any]) -> ModalityOutput:
        """Convert model output to structured ModalityOutput."""
        ...

    async def invoke(self, inputs: ModalityInput) -> ModalityOutput:
        if inputs.modality not in self.supported_modalities:
            raise ValueError(
                f"Pipeline {self.name!r} does not support modality {inputs.modality!r}. "
                f"Supported: {self.supported_modalities}"
            )
        preprocessed = await self.preprocess(inputs)
        raw = await self._forward(preprocessed)
        return await self.postprocess(raw)

    async def stream(self, inputs: ModalityInput) -> AsyncIterator[ModalityOutput]:
        """Default streaming: yield the full result once."""
        result = await self.invoke(inputs)
        yield result


class TextPipeline(BaseModalPipeline):
    """
    Text modality pipeline — wraps Zorali's existing LLM provider.
    Acts as the bridge between multi-modal inputs and the provider router.
    """

    name = "text"
    supported_modalities = ["text"]

    async def preprocess(self, inputs: ModalityInput) -> dict[str, Any]:
        return {"messages": [{"role": "user", "content": str(inputs.content)}]}

    async def _forward(self, preprocessed: dict[str, Any]) -> dict[str, Any]:
        from app.providers.provider_router import router as provider_router
        tokens = []
        async for token, provider in provider_router.stream_chat(preprocessed["messages"]):
            tokens.append(token)
        return {"text": "".join(tokens), "provider": provider}

    async def postprocess(self, raw_output: dict[str, Any]) -> ModalityOutput:
        return ModalityOutput(
            modality="text",
            content=raw_output["text"],
            metadata={"provider": raw_output.get("provider", "unknown")},
        )


class ImageDescriptionPipeline(BaseModalPipeline):
    """
    Image-to-text pipeline.
    Sends image URL to multimodal-capable model (e.g. llava, gpt-4o).
    """

    name = "image_description"
    supported_modalities = ["image"]

    async def preprocess(self, inputs: ModalityInput) -> dict[str, Any]:
        content = inputs.content
        if isinstance(content, bytes):
            import base64
            b64 = base64.b64encode(content).decode()
            url = f"data:{inputs.mime_type or 'image/jpeg'};base64,{b64}"
        else:
            url = str(content)
        return {
            "messages": [
                {"role": "user", "content": [
                    {"type": "image_url", "image_url": {"url": url}},
                    {"type": "text", "text": "Describe this image in detail."},
                ]}
            ]
        }

    async def _forward(self, preprocessed: dict[str, Any]) -> dict[str, Any]:
        from app.providers.provider_router import router as provider_router
        tokens = []
        provider = "unknown"
        async for token, prov in provider_router.stream_chat(preprocessed["messages"]):
            tokens.append(token)
            provider = prov
        return {"text": "".join(tokens), "provider": provider}

    async def postprocess(self, raw_output: dict[str, Any]) -> ModalityOutput:
        return ModalityOutput(
            modality="text",
            content=raw_output["text"],
            metadata={"source_modality": "image", "provider": raw_output.get("provider")},
        )
