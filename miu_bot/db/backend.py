"""MemoryBackend Protocol and data models for multi-tenant storage."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable


@dataclass
class Workspace:
    id: str
    name: str
    identity: str
    config_overrides: dict[str, Any]
    status: str  # active | paused | archived
    created_at: datetime
    updated_at: datetime


@dataclass
class Session:
    id: str
    workspace_id: str
    channel: str
    channel_identifier: str
    metadata: dict[str, Any]
    last_consolidated_at: datetime | None
    created_at: datetime


@dataclass
class Message:
    id: int
    session_id: str
    role: str  # user | assistant | system | tool
    content: str
    metadata: dict[str, Any]
    consolidated: bool
    created_at: datetime


@dataclass
class Memory:
    id: str
    workspace_id: str
    category: str  # fact | preference | event | summary
    content: str
    source_session_id: str | None
    created_at: datetime


@runtime_checkable
class MemoryBackend(Protocol):
    """Protocol for pluggable storage backends."""

    async def initialize(self) -> None: ...
    async def close(self) -> None: ...
    async def health_check(self) -> bool: ...

    # Workspace
    async def get_workspace(self, workspace_id: str) -> Workspace | None: ...
    async def get_workspace_by_name(self, name: str) -> Workspace | None: ...
    async def list_workspaces(self) -> list[Workspace]: ...
    async def create_workspace(
        self, name: str, identity: str, config_overrides: dict[str, Any] | None = None
    ) -> Workspace: ...
    async def update_workspace(self, workspace_id: str, **kwargs: Any) -> Workspace | None: ...
    async def delete_workspace(self, workspace_id: str) -> bool: ...

    # Session
    async def get_or_create_session(
        self, workspace_id: str, channel: str, identifier: str
    ) -> Session: ...
    async def get_session(self, session_id: str) -> Session | None: ...

    # Messages
    async def save_message(
        self, session_id: str, role: str, content: str, metadata: dict[str, Any] | None = None
    ) -> Message: ...
    async def get_messages(self, session_id: str, limit: int = 50) -> list[Message]: ...
    async def mark_consolidated(self, session_id: str, up_to_id: int) -> int: ...

    # Memories
    async def save_memory(
        self,
        workspace_id: str,
        category: str,
        content: str,
        source_session_id: str | None = None,
    ) -> Memory: ...
    async def get_memories(
        self, workspace_id: str, categories: list[str] | None = None
    ) -> list[Memory]: ...
    async def replace_memories(
        self, workspace_id: str, category: str, content: str
    ) -> None: ...
