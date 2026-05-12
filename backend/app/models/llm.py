from app.models.ollama_client import stream_chat

async def stream_llm(messages: list[dict], **kwargs):
    async for token in stream_chat(messages, model=kwargs.get("model")):
        yield token
