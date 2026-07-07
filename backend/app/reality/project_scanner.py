import subprocess
from pathlib import Path


def _run(cmd: list[str], cwd: str | None = None) -> str:
    try:
        result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=8)
        return (result.stdout or result.stderr).strip()
    except Exception as exc:
        return f"unavailable: {exc}"


def scan_project(path: str) -> dict:
    root = Path(path).resolve()
    exists = root.exists()
    files = []
    if exists:
        for p in list(root.rglob("*"))[:200]:
            if p.is_file() and not any(part in {"node_modules", ".git", "__pycache__"} for part in p.parts):
                files.append(str(p.relative_to(root)))
    git_status = _run(["git", "status", "--porcelain"], cwd=str(root)) if exists else "path not found"
    git_log = _run(["git", "log", "--oneline", "-5"], cwd=str(root)) if exists else "path not found"
    package_json = root / "package.json"
    pyproject = root / "pyproject.toml"
    requirements = root / "requirements.txt"
    return {
        "path": str(root),
        "exists": exists,
        "file_count_sampled": len(files),
        "files": files[:50],
        "git_changes": git_status.splitlines() if git_status else [],
        "recent_commits": git_log.splitlines() if git_log else [],
        "detected": {
            "node": package_json.exists(),
            "python_pyproject": pyproject.exists(),
            "python_requirements": requirements.exists(),
        },
    }


def status_report(path: str) -> dict:
    scan = scan_project(path)
    critical = []
    if not scan["exists"]:
        critical.append("Project path does not exist.")
    if scan["git_changes"]:
        critical.append(f"There are {len(scan['git_changes'])} uncommitted Git changes.")
    if not critical:
        critical.append("No critical issues detected in the quick scan.")
    return {**scan, "status_report": "\n".join(critical)}
