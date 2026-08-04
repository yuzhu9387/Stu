import pytest
from unittest.mock import AsyncMock, MagicMock

from app.services.voyage_client import VoyageClient


async def test_embed_returns_vector(monkeypatch):
    fake_result = MagicMock()
    fake_result.embeddings = [[0.5] * 1024]
    fake_aclient = MagicMock()
    fake_aclient.embed = AsyncMock(return_value=fake_result)

    monkeypatch.setattr(
        "app.services.voyage_client.voyageai.AsyncClient",
        lambda **kw: fake_aclient,
    )
    client = VoyageClient(api_key="fake")
    vec = await client.embed("hello world")
    assert isinstance(vec, list)
    assert len(vec) == 1024


async def test_embed_passes_voyage_3_model(monkeypatch):
    """Verify the client passes model='voyage-3'."""
    fake_result = MagicMock()
    fake_result.embeddings = [[0.0] * 1024]
    fake_aclient = MagicMock()
    fake_aclient.embed = AsyncMock(return_value=fake_result)

    monkeypatch.setattr(
        "app.services.voyage_client.voyageai.AsyncClient",
        lambda **kw: fake_aclient,
    )
    client = VoyageClient(api_key="fake")
    await client.embed("test")
    # voyageai.AsyncClient.embed signature: embed(texts, model=...)
    call = fake_aclient.embed.await_args
    # Tolerant matching: check kwargs or positional
    assert call is not None
    model_seen = call.kwargs.get("model")
    if model_seen is None and len(call.args) >= 2:
        model_seen = call.args[1]
    assert model_seen == "voyage-3"


async def test_embed_without_api_key_returns_empty():
    client = VoyageClient(api_key="")
    vec = await client.embed("hello")
    assert vec == []
