"""
Skill registry with dependency graph validation.
Patterns:
- OpenJarvis: build_dependency_graph() + compute_capability_union()
- HuggingFace: PipelineRegistry task mapping with alias support
- PyTorch: dict-based component registration with name as primary key
"""
from __future__ import annotations
from typing import Type
from app.skills.base import BaseSkill, SkillManifest
from app.core.audit import audit, AuditEvent


class DependencyError(Exception):
    pass


class SkillRegistry:
    """
    Central registry for all installed skills.
    Skills register themselves or are loaded by the SkillLoader.
    Validates dependency graph before allowing execution.
    """

    def __init__(self):
        self._skills: dict[str, BaseSkill] = {}
        self._manifests: dict[str, SkillManifest] = {}
        self._aliases: dict[str, str] = {}  # alias → canonical name

    def register(self, skill: BaseSkill, alias: str | None = None) -> None:
        name = skill.manifest.name
        self._validate_deps(skill.manifest)
        self._skills[name] = skill
        self._manifests[name] = skill.manifest
        if alias:
            self._aliases[alias] = name
        audit.record(
            AuditEvent.SKILL_INSTALLED,
            resource=name,
            version=skill.manifest.version,
            deps=skill.manifest.dependencies,
        )

    def unregister(self, name: str) -> None:
        canonical = self._resolve_name(name)
        self._skills.pop(canonical, None)
        self._manifests.pop(canonical, None)
        self._aliases = {k: v for k, v in self._aliases.items() if v != canonical}
        audit.record(AuditEvent.SKILL_REMOVED, resource=canonical)

    def get(self, name: str) -> BaseSkill:
        canonical = self._resolve_name(name)
        skill = self._skills.get(canonical)
        if not skill:
            raise KeyError(f"Skill not found: {name!r}")
        if not skill.manifest.enabled:
            raise RuntimeError(f"Skill {name!r} is disabled")
        return skill

    def list_skills(self) -> list[dict]:
        return [
            {
                "name": m.name,
                "version": m.version,
                "description": m.description,
                "tags": m.tags,
                "enabled": m.enabled,
                "dependencies": m.dependencies,
            }
            for m in self._manifests.values()
        ]

    def _resolve_name(self, name: str) -> str:
        return self._aliases.get(name, name)

    def _validate_deps(self, manifest: SkillManifest) -> None:
        """
        Topological dependency check.
        Prevents registration if required skills are missing.
        Mirrors TensorFlow's topological sorting validation + OpenJarvis dependency graph.
        """
        missing = [d for d in manifest.dependencies if d not in self._skills]
        if missing:
            raise DependencyError(
                f"Skill {manifest.name!r} requires uninstalled skills: {missing}. "
                "Install dependencies first."
            )

    def compute_capability_union(self) -> set[str]:
        """
        Returns the union of all tags/capabilities across installed skills.
        Mirrors OpenJarvis compute_capability_union() for routing decisions.
        """
        caps: set[str] = set()
        for m in self._manifests.values():
            if m.enabled:
                caps.update(m.tags)
        return caps


skill_registry = SkillRegistry()
