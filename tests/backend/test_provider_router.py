import pytest
from app.providers.provider_router import ProviderRouter


@pytest.mark.asyncio
async def test_provider_router_fallback(monkeypatch):
    router = ProviderRouter()

    async def fail_stream(*args, **kwargs):
        raise RuntimeError("down")
        yield

    async def ok_stream(*args, **kwargs):
        yield "ok"

    monkeypatch.setattr(router.ollama, "stream_chat", fail_stream)
    monkeypatch.setattr(router.cloud, "stream_chat", ok_stream)
    out = []
    async for token, provider in router.stream_chat([{"role": "user", "content": "hi"}], local_first=True):
        out.append((token, provider))
    assert out[0][1] == "cloud"
