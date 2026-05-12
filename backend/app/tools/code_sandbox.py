import asyncio, tempfile, os

class CodeSandbox:
    async def run_python(self, code: str, timeout: int = 5) -> dict:
        with tempfile.NamedTemporaryFile('w', suffix='.py', delete=False) as f:
            f.write(code)
            name = f.name
        try:
            proc = await asyncio.create_subprocess_exec('python', '-I', name, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return {'stdout': out.decode()[:4000], 'stderr': err.decode()[:2000], 'returncode': proc.returncode}
        except asyncio.TimeoutError:
            proc.kill()
            return {'stdout': '', 'stderr': 'timeout', 'returncode': -1}
        finally:
            try: os.unlink(name)
            except FileNotFoundError: pass
