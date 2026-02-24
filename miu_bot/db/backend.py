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
    id: str
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
    tier: str = "active"  # active | reference | archive
    source_type: str | None = None  # conversation | daily_note | weekly_insight | monthly_summary
    priority: int = 0
    expires_at: datetime | None = None


@dataclass
class DailyNote:
    id: str
    workspace_id: str
    date: datetime
    summary: str | None
    key_topics: list[str]
    decisions_made: list[str]
    action_items: list[str]
    emotional_tone: str | None
    message_count: int
    consolidated: bool
    created_at: datetime


@dataclass
class ConsolidationLogEntry:
    id: str
    workspace_id: str
    type: str  # daily | weekly | monthly
    period_start: datetime | None
    period_end: datetime | None
    input_count: int
    output_count: int
    model_used: str | None
    tokens_used: int | None
    cost_estimate: float | None
    status: str  # pending | completed | failed
    error: str | None
    created_at: datetime


@dataclass
class WorkspaceTemplate:
    id: str
    workspace_id: str
    template_type: str  # soul | user | agents | heartbeat
    content: str
    config: dict[str, Any]
    created_at: datetime
    updated_at: datetime


@dataclass
class WorkspaceSkill:
    id: str
    workspace_id: str
    name: str
    description: str
    identity: str  # Prompt fragment
    rules: list[str]
    mcp_servers: dict[str, Any]
    tags: list[str]
    source: str  # inline | local:/path | git:org/repo/skill
    source_version: str
    enabled: bool
    created_at: datetime
    updated_at: datetime


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
    async def mark_consolidated(self, session_id: str, up_to_id: str) -> int: ...

    # Memories
    async def save_memory(
        self,
        workspace_id: str,
        category: str,
        content: str,
        source_session_id: str | None = None,
        tier: str = "active",
        source_type: str | None = None,
        priority: int = 0,
    ) -> Memory: ...
    async def get_memories(
        self, workspace_id: str, categories: list[str] | None = None
    ) -> list[Memory]: ...
    async def replace_memories(
        self, workspace_id: str, category: str, content: str
    ) -> None: ...

    # Tier-filtered memories
    async def get_memories_by_tier(
        self, workspace_id: str, tier: str, limit: int = 50
    ) -> list[Memory]: ...

    # Daily notes
    async def save_daily_note(self, note: DailyNote) -> DailyNote: ...
    async def get_daily_notes(
        self, workspace_id: str, start_date: datetime, end_date: datetime
    ) -> list[DailyNote]: ...

    # Consolidation log
    async def log_consolidation(self, entry: ConsolidationLogEntry) -> None: ...

    # Unconsolidated messages (cross-session, by workspace + date range)
    async def get_unconsolidated_messages(
        self, workspace_id: str, since: datetime, until: datetime
    ) -> list[Message]: ...

    # Weekly/monthly consolidation support
    async def get_unconsolidated_daily_notes(
        self, workspace_id: str, start: datetime, end: datetime
    ) -> list[DailyNote]: ...
    async def mark_daily_notes_consolidated(
        self, workspace_id: str, note_ids: list[str]
    ) -> None: ...
    async def promote_memory_tier(
        self, memory_id: str, new_tier: str, source_type: str | None = None
    ) -> None: ...
    async def delete_expired_memories(
        self, workspace_id: str, tier: str, older_than: datetime
    ) -> int: ...
    async def delete_old_daily_notes(
        self, workspace_id: str, older_than: datetime
    ) -> int: ...

    # Workspace templates
    async def upsert_template(
        self, workspace_id: str, template_type: str, content: str,
        config: dict[str, Any] | None = None,
    ) -> WorkspaceTemplate: ...
    async def get_templates(self, workspace_id: str) -> list[WorkspaceTemplate]: ...

    # Workspace skills
    async def upsert_skill(self, workspace_id: str, skill: WorkspaceSkill) -> WorkspaceSkill: ...
    async def get_skills(
        self, workspace_id: str, enabled_only: bool = True,
    ) -> list[WorkspaceSkill]: ...
