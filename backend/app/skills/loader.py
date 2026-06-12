"""
Dynamic skill loader — discovers and installs skills from a directory.
Pattern: OpenJarvis directory-based skill manifest loading.
Skills are plain Python files with a SKILL_MANIFEST dict and a create() function.
"""
from __future__ import annotations
import importlib.util
import sys
import os
from pathlib import Path
from app.skills.base import BaseSkill, SkillManifest
from app.skills.registry import skill_registry


SKILLS_DIR = Path(__file__).parent / "installed"


def load_skill_from_file(path: Path) -> BaseSkill | None:
    """
    Load a single skill from a Python file.
    The file must expose:
    - SKILL_MANIFEST: dict  (manifest fields)
    - create() -> BaseSkill  (factory function)
    """
    spec = importlib.util.spec_from_file_location(f"skill_{path.stem}", path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[f"skill_{path.stem}"] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        print(f"[SkillLoader] Failed to load {path.name}: {exc}")
        return None
    if not hasattr(module, "SKILL_MANIFEST") or not hasattr(module, "create"):
        return None
    try:
        manifest = SkillManifest(**module.SKILL_MANIFEST)
        skill = module.create(manifest)
        return skill
    except Exception as exc:
        print(f"[SkillLoader] Invalid skill in {path.name}: {exc}")
        return None


def discover_and_load(skills_dir: Path = SKILLS_DIR) -> list[str]:
    """
    Scan a directory for skill files and register all valid skills.
    Returns list of successfully loaded skill names.
    """
    if not skills_dir.exists():
        skills_dir.mkdir(parents=True, exist_ok=True)
        return []
    loaded = []
    for py_file in sorted(skills_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        skill = load_skill_from_file(py_file)
        if skill:
            try:
                skill_registry.register(skill)
                loaded.append(skill.manifest.name)
            except Exception as exc:
                print(f"[SkillLoader] Could not register {py_file.name}: {exc}")
    return loaded
