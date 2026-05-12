class DomainGateway:
    def __init__(self, secrets=None):
        self.secrets = secrets or {}
    def redact(self, data: dict):
        return {k: ('[REDACTED]' if any(s in k.lower() for s in ['key','token','secret','password']) else v) for k,v in data.items()}
