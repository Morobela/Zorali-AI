class MCPServer:
    def __init__(self): self.tools={}
    async def handle_message(self, raw, client_id='local', client_role='user'):
        if raw.get('method') == 'initialize': return {'jsonrpc':'2.0','id':raw.get('id'),'result':{'serverInfo':{'name':'charlie-ai'}}}
        if raw.get('method') == 'tools/list': return {'jsonrpc':'2.0','id':raw.get('id'),'result':{'tools':[]}}
        return {'jsonrpc':'2.0','id':raw.get('id'),'error':{'message':'not implemented'}}
