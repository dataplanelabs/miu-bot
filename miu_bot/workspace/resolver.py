"""Workspace resolver: maps (channel, chat_id) to workspace_id."""

from __future__ import annotations

import time

from loguru import logger

from miu_bot.db.backend import MemoryBackend


class WorkspaceResolver:
    """Resolve which workspace owns a given channel + chat_id."""

    CACHE_TTL = 300  # 5 minutes

    def __init__(self, backend: MemoryBackend):
        self._backend = backend
        self._cache: dict[str, tuple[str, float]] = {}

    async def resolve(self, channel: str, chat_id: str) -> str | None:
        """Return workspace_id for the given channel:chat_id, or None."""
        key = f"{channel}:{chat_id}"
        if key in self._cache:
            ws_id, ts = self._cache[key]
            if time.monotonic() - ts < self.CACHE_TTL:
                return ws_id
            del self._cache[key]

        workspaces = await self._backend.list_workspaces()
        for ws in workspaces:
            if ws.status != "active":
                continue
            channel_cfg = ws.config_overrides.get("channels", {}).get(channel, {})
            allow_from = channel_cfg.get("allowFrom", [])
            if not allow_from or chat_id in allow_from:
                self._cache[key] = (ws.id, time.monotonic())
                return ws.id

        logger.warning(f"No workspace matched for {channel}:{chat_id} — message rejected")
        return None

    def invalidate(self, channel: str, chat_id: str) -> None:
        self._cache.pop(f"{channel}:{chat_id}", None)

    def invalidate_all(self) -> None:
        self._cache = {}
