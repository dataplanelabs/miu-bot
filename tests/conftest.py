"""Shared pytest fixtures for all test modules."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from miu_bot.db.backend import Memory, Workspace, WorkspaceSkill


@pytest.fixture
def mock_workspace():
    return Workspace(
        id="ws-001",
        name="test-workspace",
        identity="You are a test bot.",
        config_overrides={},
        status="active",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        max_budget_usd=None,
        soft_budget_usd=None,
        spend_current=0.0,
    )


@pytest.fixture
def mock_backend(mock_workspace):
    """AsyncMock MemoryBackend with sensible defaults."""
    backend = AsyncMock()
    backend.get_workspace.return_value = mock_workspace
    backend.get_or_create_session.return_value = MagicMock(id="sess-001")
    backend.get_messages.return_value = []
    backend.get_memories.return_value = []
    backend.get_memories_by_tier.return_value = []
    backend.save_message.return_value = MagicMock()
    backend.log_usage.return_value = None
    backend.get_usage_summary.return_value = {
        "request_count": 0, "total_tokens": 0, "total_cost_usd": 0
    }
    backend.get_skills.return_value = []
    return backend


@pytest.fixture
def mock_llm_provider():
    """AsyncMock LLMProvider returning a simple text response."""
    from miu_bot.providers.base import LLMResponse
    provider = AsyncMock()
    provider.get_default_model.return_value = "test-model"
    provider.chat.return_value = LLMResponse(
        content="Hello from mock LLM.",
        finish_reason="stop",
        tool_calls=[],
        usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    )
    return provider
