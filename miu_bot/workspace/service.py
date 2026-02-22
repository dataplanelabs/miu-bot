"""Workspace CRUD service using MemoryBackend."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from loguru import logger

from miu_bot.db.backend import MemoryBackend, Workspace
from miu_bot.workspace.config_merge import deep_merge
from miu_bot.workspace.identity import parse_identity


class WorkspaceService:
    """High-level workspace operations backed by MemoryBackend."""

    def __init__(self, backend: MemoryBackend):
        self._backend = backend

    async def create(
        self,
        name: str,
        identity_path: Path | None = None,
        identity_text: str | None = None,
        config_overrides: dict[str, Any] | None = None,
    ) -> Workspace:
        """Create a workspace. Reads identity from file or uses provided text."""
        identity = ""
        if identity_path and identity_path.exists():
            identity = identity_path.read_text(encoding="utf-8")
        elif identity_text:
            identity = identity_text

        # Validate identity parses
        if identity:
            parse_identity(identity)

        return await self._backend.create_workspace(name, identity, config_overrides)

    async def get(self, name: str) -> Workspace | None:
        return await self._backend.get_workspace_by_name(name)

    async def get_by_id(self, workspace_id: str) -> Workspace | None:
        return await self._backend.get_workspace(workspace_id)

    async def list(self) -> list[Workspace]:
        return await self._backend.list_workspaces()

    async def update_config(self, name: str, key: str, value: Any) -> Workspace | None:
        """Update a single config key using dot-notation."""
        ws = await self._backend.get_workspace_by_name(name)
        if not ws:
            return None
        overrides = ws.config_overrides.copy()
        # Support dot-notation: "agents.defaults.model" -> nested set
        parts = key.split(".")
        target = overrides
        for part in parts[:-1]:
            target = target.setdefault(part, {})
        target[parts[-1]] = value
        return await self._backend.update_workspace(ws.id, config_overrides=overrides)

    async def set_status(self, name: str, status: str) -> Workspace | None:
        ws = await self._backend.get_workspace_by_name(name)
        if not ws:
            return None
        valid = {"active", "paused", "archived"}
        if status not in valid:
            raise ValueError(f"Invalid status: {status}. Must be one of {valid}")
        return await self._backend.update_workspace(ws.id, status=status)

    async def delete(self, name: str) -> bool:
        ws = await self._backend.get_workspace_by_name(name)
        if not ws:
            return False
        return await self._backend.delete_workspace(ws.id)

    async def get_effective_config(
        self, workspace: Workspace, global_config_dict: dict[str, Any]
    ) -> dict[str, Any]:
        """Deep merge global config with workspace overrides."""
        return deep_merge(global_config_dict, workspace.config_overrides)
