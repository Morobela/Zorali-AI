import subprocess

async def git_status(path: str = '/workspace') -> dict:
    result = subprocess.run(['git','-C',path,'status','--porcelain'], capture_output=True, text=True, timeout=10)
    return {'changes': result.stdout.splitlines(), 'stderr': result.stderr}
