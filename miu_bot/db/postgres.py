"""PostgreSQL backend implementation using asyncpg."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

_MUTABLE_COLUMNS = {"name", "identity", "config_overrides", "status"}

from miu_bot.db.backend import (
    ConsolidationLogEntry,
    DailyNote,
    Memory,
    Message,
    Session,
    Workspace,
    WorkspaceSkill,
    WorkspaceTemplate,
)

try:
    import asyncpg
except ImportError:
    asyncpg = None  # type: ignore[assignment]


class PostgresBackend:
    """MemoryBackend implementation backed by PostgreSQL via asyncpg."""

    def __init__(self, pool: "asyncpg.Pool"):
        self._pool = pool

    async def initialize(self) -> None:
        pass  # Pool already created externally

    async def close(self) -> None:
        pass  # Pool closed externally

    async def health_check(self) -> bool:
        from miu_bot.db.pool import health_check
        return await health_check(self._pool)

    # -- Workspace CRUD --

    async def get_workspace(self, workspace_id: str) -> Workspace | None:
        row = await self._pool.fetchrow(
            "SELECT * FROM workspaces WHERE id = $1", workspace_id
        )
        return self._row_to_workspace(row) if row else None

    async def get_workspace_by_name(self, name: str) -> Workspace | None:
        row = await self._pool.fetchrow(
            "SELECT * FROM workspaces WHERE name = $1", name
        )
        return self._row_to_workspace(row) if row else None

    async def list_workspaces(self) -> list[Workspace]:
        rows = await self._pool.fetch("SELECT * FROM workspaces ORDER BY created_at")
        return [self._row_to_workspace(r) for r in rows]

    async def create_workspace(
        self, name: str, identity: str, config_overrides: dict[str, Any] | None = None
    ) -> Workspace:
        ws_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        overrides = json.dumps(config_overrides or {})
        row = await self._pool.fetchrow(
            """INSERT INTO workspaces (id, name, identity, config_overrides, status, created_at, updated_at)
               VALUES ($1, $2, $3, $4::jsonb, 'active', $5, $5)
               RETURNING *""",
            ws_id, name, identity, overrides, now,
        )
        return self._row_to_workspace(row)

    async def update_workspace(self, workspace_id: str, **kwargs: Any) -> Workspace | None:
        sets, vals, idx = [], [], 1
        for key, val in kwargs.items():
            if key not in _MUTABLE_COLUMNS:
                raise ValueError(f"Cannot update column: {key}")
            if key == "config_overrides":
                val = json.dumps(val)
                sets.append(f"config_overrides = ${idx}::jsonb")
            else:
                sets.append(f"{key} = ${idx}")
            vals.append(val)
            idx += 1
        sets.append(f"updated_at = ${idx}")
        vals.append(datetime.now(timezone.utc))
        idx += 1
        vals.append(workspace_id)
        sql = f"UPDATE workspaces SET {', '.join(sets)} WHERE id = ${idx} RETURNING *"
        row = await self._pool.fetchrow(sql, *vals)
        return self._row_to_workspace(row) if row else None

    async def delete_workspace(self, workspace_id: str) -> bool:
        tag = await self._pool.execute(
            "DELETE FROM workspaces WHERE id = $1", workspace_id
        )
        return tag == "DELETE 1"

    # -- Session --

    async def get_or_create_session(
        self, workspace_id: str, channel: str, identifier: str
    ) -> Session:
        sess_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        row = await self._pool.fetchrow(
            """INSERT INTO sessions (id, workspace_id, channel, channel_identifier, metadata, created_at)
               VALUES ($1, $2, $3, $4, '{}'::jsonb, $5)
               ON CONFLICT (workspace_id, channel, channel_identifier)
               DO UPDATE SET channel = EXCLUDED.channel
               RETURNING *""",
            sess_id, workspace_id, channel, identifier, now,
        )
        return self._row_to_session(row)

    async def get_session(self, session_id: str) -> Session | None:
        row = await self._pool.fetchrow("SELECT * FROM sessions WHERE id = $1", session_id)
        return self._row_to_session(row) if row else None

    # -- Messages --

    async def save_message(
        self, session_id: str, role: str, content: str, metadata: dict[str, Any] | None = None
    ) -> Message:
        meta_json = json.dumps(metadata or {})
        row = await self._pool.fetchrow(
            """INSERT INTO messages (session_id, role, content, metadata, consolidated, created_at)
               VALUES ($1, $2, $3, $4::jsonb, FALSE, $5)
               RETURNING *""",
            session_id, role, content, meta_json, datetime.now(timezone.utc),
        )
        return self._row_to_message(row)

    async def get_messages(self, session_id: str, limit: int = 50) -> list[Message]:
        rows = await self._pool.fetch(
            """SELECT * FROM messages
               WHERE session_id = $1
               ORDER BY created_at ASC
               LIMIT $2""",
            session_id, limit,
        )
        return [self._row_to_message(r) for r in rows]

    async def mark_consolidated(self, session_id: str, up_to_id: int) -> int:
        tag = await self._pool.execute(
            """UPDATE messages SET consolidated = TRUE
               WHERE session_id = $1 AND id <= $2 AND consolidated = FALSE""",
            session_id, up_to_id,
        )
        return int(tag.split()[-1])

    # -- Memories --

    async def save_memory(
        self,
        workspace_id: str,
        category: str,
        content: str,
        source_session_id: str | None = None,
        tier: str = "active",
        source_type: str | None = None,
        priority: int = 0,
    ) -> Memory:
        mem_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        row = await self._pool.fetchrow(
            """INSERT INTO memories (id, workspace_id, category, content, source_session_id,
                                    tier, source_type, priority, created_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
               RETURNING *""",
            mem_id, workspace_id, category, content, source_session_id,
            tier, source_type, priority, now,
        )
        return self._row_to_memory(row)

    async def get_memories(
        self, workspace_id: str, categories: list[str] | None = None
    ) -> list[Memory]:
        if categories:
            rows = await self._pool.fetch(
                """SELECT * FROM memories
                   WHERE workspace_id = $1 AND category = ANY($2)
                   ORDER BY created_at""",
                workspace_id, categories,
            )
        else:
            rows = await self._pool.fetch(
                "SELECT * FROM memories WHERE workspace_id = $1 ORDER BY created_at",
                workspace_id,
            )
        return [self._row_to_memory(r) for r in rows]

    async def replace_memories(
        self, workspace_id: str, category: str, content: str
    ) -> None:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "DELETE FROM memories WHERE workspace_id = $1 AND category = $2",
                    workspace_id, category,
                )
                await conn.execute(
                    """INSERT INTO memories (id, workspace_id, category, content, created_at)
                       VALUES ($1, $2, $3, $4, $5)""",
                    str(uuid.uuid4()), workspace_id, category, content, datetime.now(timezone.utc),
                )

    # -- Tier-filtered memories --

    async def get_memories_by_tier(
        self, workspace_id: str, tier: str, limit: int = 50
    ) -> list[Memory]:
        rows = await self._pool.fetch(
            """SELECT * FROM memories
               WHERE workspace_id = $1 AND tier = $2
               ORDER BY priority DESC, created_at DESC
               LIMIT $3""",
            workspace_id, tier, limit,
        )
        return [self._row_to_memory(r) for r in rows]

    # -- Daily notes --

    async def save_daily_note(self, note: DailyNote) -> DailyNote:
        row = await self._pool.fetchrow(
            """INSERT INTO daily_notes
                   (workspace_id, date, summary, key_topics, decisions_made,
                    action_items, emotional_tone, message_count, consolidated, created_at)
               VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, $6::jsonb, $7, $8, $9, $10)
               ON CONFLICT (workspace_id, date) DO NOTHING
               RETURNING *""",
            note.workspace_id, note.date, note.summary,
            json.dumps(note.key_topics), json.dumps(note.decisions_made),
            json.dumps(note.action_items), note.emotional_tone,
            note.message_count, note.consolidated, datetime.now(timezone.utc),
        )
        if row is None:
            # Already exists — return existing
            row = await self._pool.fetchrow(
                "SELECT * FROM daily_notes WHERE workspace_id = $1 AND date = $2",
                note.workspace_id, note.date,
            )
        return self._row_to_daily_note(row)

    async def get_daily_notes(
        self, workspace_id: str, start_date: datetime, end_date: datetime
    ) -> list[DailyNote]:
        rows = await self._pool.fetch(
            """SELECT * FROM daily_notes
               WHERE workspace_id = $1 AND date >= $2 AND date < $3
               ORDER BY date""",
            workspace_id, start_date.date() if hasattr(start_date, 'date') else start_date,
            end_date.date() if hasattr(end_date, 'date') else end_date,
        )
        return [self._row_to_daily_note(r) for r in rows]

    # -- Consolidation log --

    async def log_consolidation(self, entry: ConsolidationLogEntry) -> None:
        await self._pool.execute(
            """INSERT INTO consolidation_log
                   (workspace_id, type, period_start, period_end, input_count,
                    output_count, model_used, tokens_used, cost_estimate, status, error, created_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)""",
            entry.workspace_id, entry.type, entry.period_start, entry.period_end,
            entry.input_count, entry.output_count, entry.model_used,
            entry.tokens_used, entry.cost_estimate, entry.status,
            entry.error, datetime.now(timezone.utc),
        )

    # -- Unconsolidated messages (cross-session) --

    async def get_unconsolidated_messages(
        self, workspace_id: str, since: datetime, until: datetime
    ) -> list[Message]:
        rows = await self._pool.fetch(
            """SELECT m.* FROM messages m
               JOIN sessions s ON m.session_id = s.id
               WHERE s.workspace_id = $1
                 AND m.consolidated = FALSE
                 AND m.created_at >= $2
                 AND m.created_at < $3
               ORDER BY m.created_at""",
            workspace_id, since, until,
        )
        return [self._row_to_message(r) for r in rows]

    # -- Weekly/monthly consolidation --

    async def get_unconsolidated_daily_notes(
        self, workspace_id: str, start: datetime, end: datetime
    ) -> list[DailyNote]:
        rows = await self._pool.fetch(
            """SELECT * FROM daily_notes
               WHERE workspace_id = $1
                 AND date >= $2 AND date < $3
                 AND consolidated = FALSE
               ORDER BY date""",
            workspace_id,
            start.date() if hasattr(start, "date") and callable(start.date) else start,
            end.date() if hasattr(end, "date") and callable(end.date) else end,
        )
        return [self._row_to_daily_note(r) for r in rows]

    async def mark_daily_notes_consolidated(
        self, workspace_id: str, note_ids: list[str]
    ) -> None:
        await self._pool.execute(
            """UPDATE daily_notes SET consolidated = TRUE
               WHERE workspace_id = $1 AND id = ANY($2::uuid[])""",
            workspace_id, note_ids,
        )

    async def promote_memory_tier(
        self, memory_id: str, new_tier: str, source_type: str | None = None
    ) -> None:
        if source_type:
            await self._pool.execute(
                "UPDATE memories SET tier = $2, source_type = $3 WHERE id = $1",
                memory_id, new_tier, source_type,
            )
        else:
            await self._pool.execute(
                "UPDATE memories SET tier = $2 WHERE id = $1",
                memory_id, new_tier,
            )

    async def delete_expired_memories(
        self, workspace_id: str, tier: str, older_than: datetime
    ) -> int:
        tag = await self._pool.execute(
            """DELETE FROM memories
               WHERE workspace_id = $1 AND tier = $2 AND created_at < $3""",
            workspace_id, tier, older_than,
        )
        return int(tag.split()[-1])

    async def delete_old_daily_notes(
        self, workspace_id: str, older_than: datetime
    ) -> int:
        tag = await self._pool.execute(
            """DELETE FROM daily_notes
               WHERE workspace_id = $1 AND date < $2""",
            workspace_id,
            older_than.date() if hasattr(older_than, "date") and callable(older_than.date) else older_than,
        )
        return int(tag.split()[-1])

    # -- Workspace templates --

    async def upsert_template(
        self, workspace_id: str, template_type: str, content: str,
        config: dict[str, Any] | None = None,
    ) -> WorkspaceTemplate:
        tmpl_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        config_json = json.dumps(config or {})
        row = await self._pool.fetchrow(
            """INSERT INTO workspace_templates
                   (id, workspace_id, template_type, content, config, created_at, updated_at)
               VALUES ($1, $2, $3, $4, $5::jsonb, $6, $6)
               ON CONFLICT (workspace_id, template_type) DO UPDATE
               SET content = EXCLUDED.content, config = EXCLUDED.config,
                   updated_at = EXCLUDED.updated_at
               RETURNING *""",
            tmpl_id, workspace_id, template_type, content, config_json, now,
        )
        return self._row_to_template(row)

    async def get_templates(self, workspace_id: str) -> list[WorkspaceTemplate]:
        rows = await self._pool.fetch(
            "SELECT * FROM workspace_templates WHERE workspace_id = $1 ORDER BY template_type",
            workspace_id,
        )
        return [self._row_to_template(r) for r in rows]

    # -- Workspace skills --

    async def upsert_skill(
        self, workspace_id: str, skill: WorkspaceSkill,
    ) -> WorkspaceSkill:
        skill_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        row = await self._pool.fetchrow(
            """INSERT INTO workspace_skills
                   (id, workspace_id, name, description, identity, rules, mcp_servers,
                    tags, source, source_version, enabled, created_at, updated_at)
               VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8::jsonb,
                       $9, $10, $11, $12, $12)
               ON CONFLICT (workspace_id, name) DO UPDATE
               SET description = EXCLUDED.description, identity = EXCLUDED.identity,
                   rules = EXCLUDED.rules, mcp_servers = EXCLUDED.mcp_servers,
                   tags = EXCLUDED.tags, source = EXCLUDED.source,
                   source_version = EXCLUDED.source_version, enabled = EXCLUDED.enabled,
                   updated_at = EXCLUDED.updated_at
               RETURNING *""",
            skill_id, workspace_id, skill.name, skill.description, skill.identity,
            json.dumps(skill.rules), json.dumps(skill.mcp_servers),
            json.dumps(skill.tags), skill.source, skill.source_version,
            skill.enabled, now,
        )
        return self._row_to_skill(row)

    async def get_skills(
        self, workspace_id: str, enabled_only: bool = True,
    ) -> list[WorkspaceSkill]:
        if enabled_only:
            rows = await self._pool.fetch(
                """SELECT * FROM workspace_skills
                   WHERE workspace_id = $1 AND enabled = TRUE
                   ORDER BY name""",
                workspace_id,
            )
        else:
            rows = await self._pool.fetch(
                "SELECT * FROM workspace_skills WHERE workspace_id = $1 ORDER BY name",
                workspace_id,
            )
        return [self._row_to_skill(r) for r in rows]

    # -- Row mappers --

    @staticmethod
    def _row_to_workspace(row: Any) -> Workspace:
        overrides = row["config_overrides"]
        if isinstance(overrides, str):
            overrides = json.loads(overrides)
        return Workspace(
            id=row["id"], name=row["name"], identity=row["identity"],
            config_overrides=overrides or {},
            status=row["status"],
            created_at=row["created_at"], updated_at=row["updated_at"],
        )

    @staticmethod
    def _row_to_session(row: Any) -> Session:
        meta = row["metadata"]
        if isinstance(meta, str):
            meta = json.loads(meta)
        return Session(
            id=row["id"], workspace_id=row["workspace_id"],
            channel=row["channel"], channel_identifier=row["channel_identifier"],
            metadata=meta or {},
            last_consolidated_at=row.get("last_consolidated_at"),
            created_at=row["created_at"],
        )

    @staticmethod
    def _row_to_message(row: Any) -> Message:
        meta = row["metadata"]
        if isinstance(meta, str):
            meta = json.loads(meta)
        return Message(
            id=row["id"], session_id=row["session_id"],
            role=row["role"], content=row["content"],
            metadata=meta or {},
            consolidated=row["consolidated"], created_at=row["created_at"],
        )

    @staticmethod
    def _row_to_memory(row: Any) -> Memory:
        return Memory(
            id=row["id"], workspace_id=row["workspace_id"],
            category=row["category"], content=row["content"],
            source_session_id=row.get("source_session_id"),
            created_at=row["created_at"],
            tier=row.get("tier", "active"),
            source_type=row.get("source_type"),
            priority=row.get("priority", 0),
            expires_at=row.get("expires_at"),
        )

    @staticmethod
    def _row_to_daily_note(row: Any) -> DailyNote:
        topics = row.get("key_topics", [])
        if isinstance(topics, str):
            topics = json.loads(topics)
        decisions = row.get("decisions_made", [])
        if isinstance(decisions, str):
            decisions = json.loads(decisions)
        items = row.get("action_items", [])
        if isinstance(items, str):
            items = json.loads(items)
        return DailyNote(
            id=str(row["id"]), workspace_id=row["workspace_id"],
            date=row["date"], summary=row.get("summary"),
            key_topics=topics or [], decisions_made=decisions or [],
            action_items=items or [], emotional_tone=row.get("emotional_tone"),
            message_count=row.get("message_count", 0),
            consolidated=row.get("consolidated", False),
            created_at=row["created_at"],
        )

    @staticmethod
    def _row_to_template(row: Any) -> WorkspaceTemplate:
        config = row["config"]
        if isinstance(config, str):
            config = json.loads(config)
        return WorkspaceTemplate(
            id=row["id"], workspace_id=row["workspace_id"],
            template_type=row["template_type"], content=row["content"],
            config=config or {},
            created_at=row["created_at"], updated_at=row["updated_at"],
        )

    @staticmethod
    def _row_to_skill(row: Any) -> WorkspaceSkill:
        rules = row["rules"]
        if isinstance(rules, str):
            rules = json.loads(rules)
        mcp = row["mcp_servers"]
        if isinstance(mcp, str):
            mcp = json.loads(mcp)
        tags = row["tags"]
        if isinstance(tags, str):
            tags = json.loads(tags)
        return WorkspaceSkill(
            id=row["id"], workspace_id=row["workspace_id"],
            name=row["name"], description=row["description"],
            identity=row["identity"], rules=rules or [],
            mcp_servers=mcp or {}, tags=tags or [],
            source=row["source"], source_version=row["source_version"],
            enabled=row["enabled"],
            created_at=row["created_at"], updated_at=row["updated_at"],
        )
