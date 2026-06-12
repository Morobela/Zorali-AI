"""
Multi-modal pipeline registry.
Pattern: HuggingFace PipelineRegistry — maps task names to pipeline classes,
supports aliases, enables task-specific pipeline discovery without tight coupling.
"""
from __future__ import annotations
from typing import Type
from app.multimodal.base import BaseModalPipeline, TextPipeline, ImageDescriptionPipeline


class PipelineRegistry:
    """
    Registry mapping task names to pipeline implementations.
    Supports task aliases and graceful fallback to text pipeline.
    """

    def __init__(self):
        self._pipelines: dict[str, BaseModalPipeline] = {}
        self._aliases: dict[str, str] = {}

    def register(self, task: str, pipeline: BaseModalPipeline, aliases: list[str] | None = None) -> None:
        self._pipelines[task] = pipeline
        for alias in (aliases or []):
            self._aliases[alias] = task

    def get(self, task: str) -> BaseModalPipeline:
        canonical = self._aliases.get(task, task)
        pipeline = self._pipelines.get(canonical)
        if pipeline is None:
            # Graceful degradation: fall back to text pipeline
            return self._pipelines.get("text-generation", TextPipeline())
        return pipeline

    def list_tasks(self) -> list[dict]:
        result = []
        for task, pipeline in self._pipelines.items():
            result.append({
                "task": task,
                "pipeline": pipeline.name,
                "supported_modalities": pipeline.supported_modalities,
            })
        return result


pipeline_registry = PipelineRegistry()

# Register built-in pipelines
pipeline_registry.register("text-generation", TextPipeline(), aliases=["chat", "text"])
pipeline_registry.register(
    "image-to-text", ImageDescriptionPipeline(),
    aliases=["image-description", "vision", "image"],
)
