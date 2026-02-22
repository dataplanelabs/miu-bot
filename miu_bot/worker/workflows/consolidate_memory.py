"""ConsolidateMemory workflow — scheduled memory consolidation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from miu_bot.db.backend import MemoryBackend
    from miu_bot.providers.base import LLMProvider


class ConsolidateMemoryWorkflow:
    """Scheduled workflow for consolidating old messages into memories.

    Runs on cron: */30 * * * *
    """

    def __init__(self, backend: "MemoryBackend", provider: "LLMProvider", model: str):
        self.backend = backend
        self.provider = provider
        self.model = model

    async def process(self) -> dict:
        """Find sessions with many unconsolidated messages and consolidate."""
        workspaces = await self.backend.list_workspaces()
        total_consolidated = 0

        for ws in workspaces:
            if ws.status != "active":
                continue
            # Get memories for this workspace (to provide context)
            memories = await self.backend.get_memories(ws.id, categories=["fact"])
            current_memory = "\n".join(m.content for m in memories)

            # NOTE: In a full implementation, we'd query sessions with
            # unconsolidated message counts > threshold. For now, this
            # workflow structure is ready for the Hatchet scheduler.
            logger.debug(f"Consolidation check for workspace {ws.name}")

        return {"consolidated": total_consolidated}
