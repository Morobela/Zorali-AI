"""Subprocess sandbox for running model- or user-authored Python.

Containment measures:
- ``python -I`` (isolated mode): no site-packages, no user site, no
  PYTHONPATH/PYTHONSTARTUP influence, script directory not on sys.path.
- Fresh temp working directory per run, deleted afterwards.
- Minimal environment (PATH only) so server secrets in env vars never leak.
- Hard wall-clock timeout (CODE_EXECUTION_TIMEOUT_SECONDS) and capped output.

Honest limits: this is process isolation, NOT a container or VM — the code
can still use the network and read world-readable files. That is why the
whole feature ships behind CODE_EXECUTION_ENABLED=false and an admin-role
gate; enable it only on trusted single-admin deployments.
"""
import asyncio
import shutil
import sys
import tempfile
from pathlib import Path

from app.core.config import settings

MAX_STDOUT = 4000
MAX_STDERR = 2000


class CodeSandbox:
    async def run_python(self, code: str, timeout: int | None = None) -> dict:
        timeout = timeout or settings.code_execution_timeout_seconds
        workdir = Path(tempfile.mkdtemp(prefix="zorali-sandbox-"))
        script = workdir / "snippet.py"
        script.write_text(code, encoding="utf-8")
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-I", str(script),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(workdir),
                env={"PATH": "/usr/bin:/bin"},
            )
            try:
                out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return {"stdout": "", "stderr": f"timeout after {timeout}s", "returncode": -1}
            return {
                "stdout": out.decode(errors="replace")[:MAX_STDOUT],
                "stderr": err.decode(errors="replace")[:MAX_STDERR],
                "returncode": proc.returncode,
            }
        finally:
            shutil.rmtree(workdir, ignore_errors=True)


code_sandbox = CodeSandbox()
