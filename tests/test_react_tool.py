"""Unit tests for miu_bot.agent.tools.react.ReactTool and BaseChannel.react no-op."""
from unittest.mock import AsyncMock

import pytest

from miu_bot.agent.tools.react import ReactTool
from miu_bot.channels.base import BaseChannel


# ---------------------------------------------------------------------------
# BaseChannel.react default (no-op)
# ---------------------------------------------------------------------------

async def test_base_channel_react_is_noop():
    """BaseChannel.react() exists and does not raise."""

    class _MinimalChannel(BaseChannel):
        name = "minimal"

        async def start(self): pass
        async def stop(self): pass
        async def send(self, msg): pass

    # Patch required __init__ deps with mocks
    ch = _MinimalChannel.__new__(_MinimalChannel)
    # Call the no-op directly — must not raise
    await BaseChannel.react(ch, "chat-1", "msg-1", "👍")


# ---------------------------------------------------------------------------
# ReactTool.execute — success paths
# ---------------------------------------------------------------------------

async def test_react_tool_calls_channel_react():
    mock_channel = AsyncMock()
    tool = ReactTool(
        get_channel_fn=lambda _: mock_channel,
        get_context_fn=lambda: ("telegram", "chat-1", "msg-100"),
    )
    result = await tool.execute(emoji="👍")
    mock_channel.react.assert_called_once_with("chat-1", "msg-100", "👍")
    assert "👍" in result


async def test_react_tool_uses_provided_message_id():
    mock_channel = AsyncMock()
    tool = ReactTool(
        get_channel_fn=lambda _: mock_channel,
        get_context_fn=lambda: ("telegram", "chat-1", "msg-latest"),
    )
    await tool.execute(emoji="❤️", message_id="msg-specific")
    mock_channel.react.assert_called_once_with("chat-1", "msg-specific", "❤️")


async def test_react_tool_falls_back_to_latest_message_id_when_not_provided():
    mock_channel = AsyncMock()
    tool = ReactTool(
        get_channel_fn=lambda _: mock_channel,
        get_context_fn=lambda: ("telegram", "chat-99", "msg-fallback"),
    )
    result = await tool.execute(emoji="🔥")
    mock_channel.react.assert_called_once_with("chat-99", "msg-fallback", "🔥")
    assert "msg-fallback" in result


# ---------------------------------------------------------------------------
# ReactTool.execute — error paths
# ---------------------------------------------------------------------------

async def test_react_tool_returns_error_when_channel_missing():
    tool = ReactTool(
        get_channel_fn=lambda _: None,
        get_context_fn=lambda: ("telegram", "chat-1", "msg-1"),
    )
    result = await tool.execute(emoji="👍")
    assert "not found" in result.lower()


async def test_react_tool_returns_error_when_no_message_id():
    mock_channel = AsyncMock()
    tool = ReactTool(
        get_channel_fn=lambda _: mock_channel,
        get_context_fn=lambda: ("telegram", "chat-1", ""),  # empty latest id
    )
    result = await tool.execute(emoji="👍")
    assert "no message_id" in result.lower()
    mock_channel.react.assert_not_called()


# ---------------------------------------------------------------------------
# ReactTool metadata
# ---------------------------------------------------------------------------

def test_react_tool_name():
    tool = ReactTool(get_channel_fn=lambda _: None, get_context_fn=lambda: ("", "", ""))
    assert tool.name == "react"


def test_react_tool_parameters_schema():
    tool = ReactTool(get_channel_fn=lambda _: None, get_context_fn=lambda: ("", "", ""))
    params = tool.parameters
    assert params["type"] == "object"
    assert "emoji" in params["properties"]
    assert "emoji" in params["required"]
