"""Unit tests for miu_bot.memory.embeddings — all LiteLLM calls mocked."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from miu_bot.memory.embeddings import generate_embedding


async def test_generate_embedding_returns_list_on_success():
    mock_resp = MagicMock()
    mock_resp.data = [{"embedding": [0.1] * 1536}]
    with patch("litellm.aembedding", new=AsyncMock(return_value=mock_resp)):
        result = await generate_embedding("hello world")
    assert result is not None
    assert isinstance(result, list)
    assert len(result) == 1536
    assert result[0] == pytest.approx(0.1)


async def test_generate_embedding_returns_none_on_exception():
    with patch("litellm.aembedding", new=AsyncMock(side_effect=Exception("API error"))):
        result = await generate_embedding("hello world")
    assert result is None


async def test_generate_embedding_uses_default_model():
    mock_resp = MagicMock()
    mock_resp.data = [{"embedding": [0.0] * 1536}]
    with patch("litellm.aembedding", new=AsyncMock(return_value=mock_resp)) as mock_call:
        result = await generate_embedding("some text")
    mock_call.assert_called_once_with(model="text-embedding-3-small", input=["some text"])
    assert result is not None


async def test_generate_embedding_uses_custom_model():
    mock_resp = MagicMock()
    mock_resp.data = [{"embedding": [0.5] * 768}]
    with patch("litellm.aembedding", new=AsyncMock(return_value=mock_resp)) as mock_call:
        result = await generate_embedding("text", model="text-embedding-ada-002")
    mock_call.assert_called_once_with(model="text-embedding-ada-002", input=["text"])
    assert result is not None
    assert len(result) == 768


async def test_generate_embedding_returns_none_on_network_error():
    with patch("litellm.aembedding", new=AsyncMock(side_effect=ConnectionError("timeout"))):
        result = await generate_embedding("test")
    assert result is None


async def test_generate_embedding_empty_string():
    """Empty string should still call the API — graceful degradation on failure."""
    with patch("litellm.aembedding", new=AsyncMock(side_effect=Exception("empty input"))):
        result = await generate_embedding("")
    assert result is None
