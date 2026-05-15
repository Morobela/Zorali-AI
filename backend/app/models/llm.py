from app.providers.provider_router import router

async def stream_llm(messages: list[dict], **kwargs):
    async for token, provider in router.stream_chat(messages, model=kwargs.get("model"), local_first=kwargs.get("local_first", True)):
        yield token
