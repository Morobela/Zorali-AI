import json
import time
from pathlib import Path
class DurableWorkflowRuntime:
    CHECKPOINT_DIR = Path('/data/workflow-checkpoints')
    def __init__(self): self.CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    async def run(self, workflow_id: str, steps: list, initial_state: dict):
        state = dict(initial_state)
        for i, step in enumerate(steps):
            state.update(await step['fn'](state))
            (self.CHECKPOINT_DIR / f'{workflow_id}.jsonl').open('a').write(json.dumps({'step': i, 'state': state, 'ts': time.time()})+'\n')
        return {'status': 'completed', 'final_state': state}
