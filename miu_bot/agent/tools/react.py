"""ReactTool — lets the agent react to messages with emoji."""

from __future__ import annotations

from typing import Any, Callable

from miu_bot.agent.tools.base import Tool


class ReactTool(Tool):
    """Tool to react to a message with an emoji on any supported channel."""

    def __init__(
        self,
        get_channel_fn: Callable[[str], Any | None],
        get_context_fn: Callable[[], tuple[str, str, str]],
    ) -> None:
        """
        Args:
            get_channel_fn: channel_name -> BaseChannel | None
            get_context_fn: () -> (channel_name, chat_id, latest_message_id)
        """
        self._get_channel = get_channel_fn
        self._get_context = get_context_fn

    @property
    def name(self) -> str:
        return "react"

    @property
    def description(self) -> str:
        return (
            "React to a message with an emoji. Use to acknowledge a message "
            "or express sentiment without sending a full text reply."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "emoji": {
                    "type": "string",
                    "description": "Unicode emoji to react with, e.g. '👍' or '❤️'",
                },
                "message_id": {
                    "type": "string",
                    "description": (
                        "ID of message to react to. "
                        "Omit to react to the most recent message."
                    ),
                },
            },
            "required": ["emoji"],
        }

    async def execute(self, emoji: str, message_id: str = "", **kwargs: Any) -> str:
        channel_name, chat_id, latest_message_id = self._get_context()
        target_id = message_id or latest_message_id
        if not target_id:
            return "No message_id available to react to."
        channel = self._get_channel(channel_name)
        if channel is None:
            return f"Channel '{channel_name}' not found."
        await channel.react(chat_id, target_id, emoji)
        return f"Reacted with {emoji} to message {target_id}."
