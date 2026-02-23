"""Poll Temporal workflow query for streaming state updates."""

from __future__ import annotations

import asyncio
from typing import Any, TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from temporalio.client import Client


class StreamingPoller:
    """Polls BotSessionWorkflow.get_streaming_state() and forwards to channel."""

    def __init__(self, client: "Client", debounce_interval: float = 1.5):
        self._client = client
        self._debounce = debounce_interval

    async def poll_and_forward(
        self,
        workflow_id: str,
        channel_adapter: Any,
        chat_id: str,
        message_id: str,
    ) -> None:
        """Poll workflow streaming state until done."""
        last_content = ""
        while True:
            try:
                handle = self._client.get_workflow_handle(workflow_id)
                state = await handle.query("get_streaming_state")

                content = state.get("content", "")
                is_done = state.get("is_done", False)

                if content != last_content and hasattr(channel_adapter, "supports_streaming") and channel_adapter.supports_streaming:
                    await channel_adapter.edit_message(
                        chat_id, message_id, content
                    )
                    last_content = content

                if is_done:
                    break

            except Exception as e:
                logger.warning(f"Streaming poll error for {workflow_id}: {e}")
                break

            await asyncio.sleep(self._debounce)
