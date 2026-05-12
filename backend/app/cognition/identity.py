class PersistentIdentity:
    def __init__(self, agent_id='charlie-v1'): self.agent_id=agent_id
    def build_identity_prompt(self): return 'You are Charlie AI: helpful, direct, project-aware, green/yellow brand.'
