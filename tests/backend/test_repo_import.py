"""Repository import and bulk upload (capability map U6).

The DoD is the last test: import Zorali-AI itself into a project and ask
accurate questions about its own source. The clone step is the one seam that
touches the network, so it is redirected at the checkout this suite is
running from — everything else (walk, filter, save_file, extract, chunk,
index, retrieval) runs for real against Postgres.

The rest covers what keeps a server-side "clone this URL" endpoint safe:
strict repository validation, credential handling, and the filters that stop
one import from swallowing a disk.
"""
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import app as app_package
from app.core.config import settings
from app.db.repositories import repo
from app.ingestion import github_import
from app.ingestion.github_import import (
    ImportError_,
    collect_files,
    parse_repo,
    run_import,
    validate_ref,
)
from app.main import app

from conftest import TEST_USER_SUB

client = TestClient(app)

REPO_ROOT = Path(app_package.__file__).resolve().parents[2]


def _project(name: str) -> dict:
    return client.post("/api/project", json={"name": f"{name}-{uuid4().hex[:6]}"}).json()


# ── repository validation (the SSRF gate) ────────────────────────────────────

@pytest.mark.parametrize("source,expected", [
    ("Morobela/Zorali-AI", ("Morobela", "Zorali-AI")),
    ("https://github.com/Morobela/Zorali-AI", ("Morobela", "Zorali-AI")),
    ("https://www.github.com/Morobela/Zorali-AI/", ("Morobela", "Zorali-AI")),
    ("https://github.com/Morobela/Zorali-AI.git", ("Morobela", "Zorali-AI")),
    ("  Morobela/Zorali-AI  ", ("Morobela", "Zorali-AI")),
])
def test_parse_repo_accepts_supported_forms(source, expected):
    assert parse_repo(source) == expected


@pytest.mark.parametrize("source", [
    "",
    "not-a-repo",
    "http://github.com/o/r",                     # plaintext
    "https://gitlab.com/o/r",                    # another host
    "https://github.evil.com/o/r",               # lookalike host
    "https://github.com/o/r/../../etc/passwd",   # traversal
    "https://127.0.0.1/o/r",                     # loopback (SSRF)
    "https://github.com:22/o/r",                 # port
    "git@github.com:o/r.git",                    # scp syntax
    "file:///etc/passwd",                        # local file
    "/etc/passwd",
    "o/r; rm -rf /",                             # shell metacharacters
    "https://user:pass@github.com/o/r",          # embedded credentials
    "../../etc/passwd",
])
def test_parse_repo_rejects_everything_else(source):
    with pytest.raises(ImportError_):
        parse_repo(source)


@pytest.mark.parametrize("ref", ["--upload-pack=evil", "-x", "a b", "branch\nname", "a" * 300])
def test_validate_ref_rejects_option_like_and_malformed_refs(ref):
    with pytest.raises(ImportError_):
        validate_ref(ref)


def test_validate_ref_accepts_normal_names():
    assert validate_ref("main") == "main"
    assert validate_ref("release/1.2.3") == "release/1.2.3"
    assert validate_ref(None) == ""


def test_error_text_never_leaks_a_token():
    scrubbed = github_import._scrub(
        "fatal: could not read https://x-access-token:ghp_supersecret@github.com/o/r", "ghp_supersecret"
    )
    assert "ghp_supersecret" not in scrubbed
    assert "***" in scrubbed


# ── file selection ───────────────────────────────────────────────────────────

def _make_tree(root: Path) -> None:
    (root / "src").mkdir(parents=True)
    (root / "node_modules" / "pkg").mkdir(parents=True)
    (root / ".git").mkdir()
    (root / "src" / "main.py").write_text("print('hello')\n")
    (root / "README.md").write_text("# readme\n")
    (root / "Dockerfile").write_text("FROM python:3.11\n")
    (root / "src" / "app.min.js").write_text("var a=1;\n")
    (root / "node_modules" / "pkg" / "index.js").write_text("module.exports={}\n")
    (root / ".git" / "config").write_text("[core]\n")
    (root / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (root / "empty.py").write_text("")


def test_collect_files_filters_the_tree(tmp_path):
    _make_tree(tmp_path)
    selected, skipped = collect_files(tmp_path)
    paths = {str(p) for p in selected}

    assert "src/main.py" in paths
    assert "README.md" in paths
    assert "Dockerfile" in paths
    assert "src/app.min.js" in paths
    # Dependency and VCS directories never enter a project.
    assert not any("node_modules" in p for p in paths)
    assert not any(".git" in p for p in paths)
    # Binary and empty files are recorded as skipped, not imported.
    assert "logo.png" not in paths
    reasons = {entry["path"]: entry["reason"] for entry in skipped}
    assert reasons.get("empty.py") == "empty"
    assert "logo.png" in reasons


def test_collect_files_skips_lockfiles(tmp_path):
    """Huge machine-generated manifests crowd real source out of retrieval."""
    (tmp_path / "package-lock.json").write_text('{"lockfileVersion": 3}\n')
    (tmp_path / "poetry.lock").write_text("[[package]]\n")
    (tmp_path / "app.py").write_text("x = 1\n")
    selected, skipped = collect_files(tmp_path)
    assert [str(p) for p in selected] == ["app.py"]
    assert {e["reason"] for e in skipped} == {"lockfile"}


def test_collect_files_honours_size_and_count_caps(tmp_path, monkeypatch):
    (tmp_path / "big.py").write_text("x" * 4096)
    (tmp_path / "small.py").write_text("y")
    monkeypatch.setattr(settings, "import_max_file_kb", 1)
    selected, skipped = collect_files(tmp_path)
    assert [str(p) for p in selected] == ["small.py"]
    assert any("larger than" in entry["reason"] for entry in skipped)

    for i in range(5):
        (tmp_path / f"f{i}.py").write_text("z")
    monkeypatch.setattr(settings, "import_max_files", 3)
    selected, skipped = collect_files(tmp_path)
    assert len(selected) == 3
    assert any("file cap reached" in entry["reason"] for entry in skipped)


# ── API surface ──────────────────────────────────────────────────────────────

def test_import_endpoint_rejects_a_bad_repository():
    project = _project("import-bad")
    res = client.post(
        f"/api/project/{project['id']}/import/github", json={"repo": "https://gitlab.com/o/r"}
    )
    assert res.status_code == 400
    assert "github.com" in res.json()["detail"]


def test_import_endpoint_404s_for_a_project_the_caller_does_not_own():
    res = client.post(f"/api/project/{uuid4()}/import/github", json={"repo": "o/r"})
    assert res.status_code == 404


def test_import_row_is_owner_scoped():
    async def _other_users_import():
        from app.db.models import User
        from app.db.session import SessionLocal

        async with SessionLocal() as session:
            async with session.begin():
                session.add(User(id="other-import-user", email="other-import@zorali.local", role="user"))
        return await repo.create_import(
            project_id="default", source="someone/else", owner_id="other-import-user"
        )

    record = asyncio.run(_other_users_import())
    assert asyncio.run(repo.get_import(record["id"], owner_id=TEST_USER_SUB)) is None


# ── bulk upload ──────────────────────────────────────────────────────────────

def test_batch_upload_accepts_many_files_and_rejects_per_file():
    project = _project("batch")
    res = client.post(
        f"/api/files/upload-batch?project_id={project['id']}",
        files=[
            ("files", ("a.txt", b"alpha content", "text/plain")),
            ("files", ("b.md", b"# beta", "text/markdown")),
            ("files", ("virus.exe", b"MZ", "application/octet-stream")),
        ],
    )
    assert res.status_code == 202
    body = res.json()
    assert body["accepted"] == 2 and body["rejected"] == 1

    rejected = [f for f in body["files"] if f["status"] == "rejected"]
    assert rejected[0]["filename"] == "virus.exe"
    # One bad file does not sink the batch: the good ones indexed.
    listed = client.get(f"/api/files/list?project_id={project['id']}").json()
    assert {f["filename"] for f in listed} == {"a.txt", "b.md"}
    assert all(f["indexing_status"] == "ready" for f in listed)


def test_batch_upload_enforces_a_file_count_ceiling(monkeypatch):
    monkeypatch.setattr(settings, "max_batch_upload_files", 2)
    project = _project("batch-cap")
    res = client.post(
        f"/api/files/upload-batch?project_id={project['id']}",
        files=[("files", (f"f{i}.txt", b"data", "text/plain")) for i in range(3)],
    )
    assert res.status_code == 400
    assert "Too many files" in res.json()["detail"]


# ── the U6 definition of done ────────────────────────────────────────────────

def _local_clone(target_ref: str = ""):
    """Stand-in for the network clone: a real git clone of this checkout."""
    async def _clone(owner, name, ref, token, dest):
        subprocess.run(
            ["git", "clone", "--depth", "1", "--no-tags", str(REPO_ROOT), str(dest)],
            check=True, capture_output=True, timeout=120,
        )
    return _clone


@pytest.mark.asyncio
async def test_import_zorali_and_ask_accurate_questions_about_its_own_source(monkeypatch):
    """U6 DoD: import Zorali-AI into a project, then ask questions about its
    own source and get the right files back."""
    monkeypatch.setattr(github_import, "clone_repo", _local_clone())

    project = _project("self-knowledge")
    record = await repo.create_import(
        project_id=project["id"], source="Morobela/Zorali-AI", owner_id=TEST_USER_SUB
    )
    final = await run_import(
        record["id"], owner="Morobela", name="Zorali-AI", ref="", token=None,
        project_id=project["id"], owner_id=TEST_USER_SUB,
    )

    assert final["status"] == "completed", final.get("error")
    assert final["imported_files"] > 50, "a real checkout should yield plenty of source files"
    # Counts are honest: every file counted as imported actually indexed.
    assert final["failed_files"] == 0, [
        e for e in final["files"] if e["status"] == "failed"
    ]

    files = await repo.list_files(project["id"], owner_id=TEST_USER_SUB)
    names = {f["filename"] for f in files}
    # Paths are preserved, which is what makes a citation useful.
    assert "backend/app/agents/goal_engine.py" in names
    assert "backend/app/reality/service_health.py" in names
    assert any(n.startswith("frontend/src/") for n in names)
    # The filters held on a real repository.
    assert not any("node_modules" in n or n.startswith(".git/") for n in names)

    from app.memory.retrieval import hybrid_retriever

    async def top_files(question: str, k: int = 5) -> list[str]:
        hits = await hybrid_retriever.retrieve(
            question, top_k=k, project_id=project["id"], owner_id=TEST_USER_SUB
        ) or []
        return [h["filename"] for h in hits]

    # Ask Zorali about its own implementation; the right source files must
    # come back from the real retrieval stack.
    goal_hits = await top_files("resume unfinished goals after a restart durable goal engine")
    assert any("goal_engine.py" in f for f in goal_hits), goal_hits

    scan_hits = await top_files("probe service health TCP latency ollama postgres redis")
    assert any("service_health.py" in f for f in scan_hits), scan_hits

    # A question phrased with an identifier, the way a developer interrogates
    # their own codebase.
    tool_hits = await top_files("holdback suffix of the TOOL_CALL marker withheld from the client")
    assert any("chat_tools.py" in f for f in tool_hits), tool_hits

    # Lockfiles are excluded, so they cannot crowd out real source.
    assert not any("package-lock.json" in f for f in goal_hits + scan_hits + tool_hits)


@pytest.mark.asyncio
async def test_import_records_failure_without_leaking_the_token(monkeypatch):
    """A clone failure is recorded on the row, with any credential scrubbed."""
    async def _failing_clone(owner, name, ref, token, dest):
        raise ImportError_(f"Clone failed: fatal: repository https://x-access-token:{token}@github.com/o/r not found")

    monkeypatch.setattr(github_import, "clone_repo", _failing_clone)
    project = _project("import-fail")
    record = await repo.create_import(
        project_id=project["id"], source="o/r", owner_id=TEST_USER_SUB
    )
    final = await run_import(
        record["id"], owner="o", name="r", ref="", token="ghp_topsecret",
        project_id=project["id"], owner_id=TEST_USER_SUB,
    )

    assert final["status"] == "failed"
    assert "ghp_topsecret" not in final["error"]
    assert "***" in final["error"]


@pytest.mark.asyncio
async def test_interrupted_imports_are_reconciled_at_boot():
    """An import left mid-flight by a restart must not claim to be running."""
    record = await repo.create_import(
        project_id="default", source="o/r", owner_id=TEST_USER_SUB
    )
    await repo.update_import(record["id"], owner_id=TEST_USER_SUB, status="importing")

    assert await repo.fail_interrupted_imports() >= 1
    reconciled = await repo.get_import(record["id"], owner_id=TEST_USER_SUB)
    assert reconciled["status"] == "failed"
    assert "restart" in reconciled["error"]
