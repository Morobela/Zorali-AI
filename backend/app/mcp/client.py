class MCPClient:
    def __init__(self, server_url: str): self.server_url=server_url
    async def initialize(self): return {}
    async def list_tools(self): return []
    def as_tool_registry(self): return {}
