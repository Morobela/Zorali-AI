import asyncio
from enum import Enum
class Priority(Enum): CRITICAL=0; HIGH=1; NORMAL=2; LOW=3; IDLE=4
class CognitiveScheduler:
    async def start(self): pass
    async def submit_fn(self, name, priority, fn, *args, **kwargs):
        if asyncio.iscoroutinefunction(fn): return await fn(*args)
        return fn(*args)
