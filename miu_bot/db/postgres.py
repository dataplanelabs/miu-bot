"""PostgreSQL backend implementation using asyncpg."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

_MUTABLE_COLUMNS = {
    "name", "identity", "config_overrides", "status",
    # MIU-26: budget columns
    "max_budget_usd", "soft_budget_usd", "budget_duration", "budget_reset_at", "spend_current",
}

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
        overrides = json.dumps(config_overrides or {})
        row = await self._pool.fetchrow(
            """INSERT INTO workspaces (name, identity, config_overrides)
               VALUES ($1, $2, $3::jsonb) RETURNING *""",
            name, identity, overrides,
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
        row = await self._pool.fetchrow(
            """INSERT INTO sessions (workspace_id, channel, channel_identifier)
               VALUES ($1, $2, $3)
               ON CONFLICT (workspace_id, channel, channel_identifier)
               DO UPDATE SET channel = EXCLUDED.channel
               RETURNING *""",
            workspace_id, channel, identifier,
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
            """INSERT INTO messages (session_id, role, content, metadata)
               VALUES ($1, $2, $3, $4::jsonb) RETURNING *""",
            session_id, role, content, meta_json,
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

    async def mark_consolidated(self, session_id: str, up_to_id: str) -> int:
        tag = await self._pool.execute(
            """UPDATE messages SET consolidated = TRUE
               WHERE session_id = $1 AND consolidated = FALSE
                 AND id <= $2::uuid""",
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
        embedding_model: str | None = None,
    ) -> Memory:
        embedding: list[float] | None = None
        if embedding_model:
            from miu_bot.memory.embeddings import generate_embedding
            embedding = await generate_embedding(content, embedding_model)

        if embedding:
            row = await self._pool.fetchrow(
                """INSERT INTO memories
                       (workspace_id, category, content, source_session_id,
                        tier, source_type, priority, embedding)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8::vector)
                   RETURNING *""",
                workspace_id, category, content, source_session_id,
                tier, source_type, priority, json.dumps(embedding),
            )
        else:
            row = await self._pool.fetchrow(
                """INSERT INTO memories
                       (workspace_id, category, content, source_session_id,
                        tier, source_type, priority)
                   VALUES ($1, $2, $3, $4, $5, $6, $7)
                   RETURNING *""",
                workspace_id, category, content, source_session_id,
                tier, source_type, priority,
            )
        return self._row_to_memory(row)

    async def search_memories_semantic(
        self,
        workspace_id: str,
        query: str,
        limit: int = 10,
        category: str | None = None,
        embedding_model: str = "text-embedding-3-small",
    ) -> list[Memory]:
        """Return top-K memories by cosine similarity. Falls back to active tier on embedding failure."""
        from miu_bot.memory.embeddings import generate_embedding, vector_search

        query_embedding = await generate_embedding(query, embedding_model)
        if not query_embedding:
            return await self.get_memories_by_tier(workspace_id, "active", limit=limit)

        rows = await vector_search(self._pool, workspace_id, query_embedding, category, limit)
        return [self._row_to_memory(r) for r in rows]

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
                    """INSERT INTO memories (workspace_id, category, content)
                       VALUES ($1, $2, $3)""",
                    workspace_id, category, content,
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
                    action_items, emotional_tone, message_count, consolidated)
               VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, $6::jsonb, $7, $8, $9)
               ON CONFLICT (workspace_id, date) DO NOTHING
               RETURNING *""",
            note.workspace_id, note.date, note.summary,
            json.dumps(note.key_topics), json.dumps(note.decisions_made),
            json.dumps(note.action_items), note.emotional_tone,
            note.message_count, note.consolidated,
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
                    output_count, model_used, tokens_used, cost_estimate, status, error)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)""",
            entry.workspace_id, entry.type, entry.period_start, entry.period_end,
            entry.input_count, entry.output_count, entry.model_used,
            entry.tokens_used, entry.cost_estimate, entry.status,
            entry.error,
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
        config_json = json.dumps(config or {})
        row = await self._pool.fetchrow(
            """INSERT INTO workspace_templates
                   (workspace_id, template_type, content, config)
               VALUES ($1, $2, $3, $4::jsonb)
               ON CONFLICT (workspace_id, template_type) DO UPDATE
               SET content = EXCLUDED.content, config = EXCLUDED.config,
                   updated_at = now()
               RETURNING *""",
            workspace_id, template_type, content, config_json,
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
        row = await self._pool.fetchrow(
            """INSERT INTO workspace_skills
                   (workspace_id, name, description, identity, rules, mcp_servers,
                    tags, source, source_version, enabled,
                    config, handler_type, config_schema)
               VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7::jsonb,
                       $8, $9, $10, $11::jsonb, $12, $13::jsonb)
               ON CONFLICT (workspace_id, name) DO UPDATE
               SET description    = EXCLUDED.description,
                   identity       = EXCLUDED.identity,
                   rules          = EXCLUDED.rules,
                   mcp_servers    = EXCLUDED.mcp_servers,
                   tags           = EXCLUDED.tags,
                   source         = EXCLUDED.source,
                   source_version = EXCLUDED.source_version,
                   enabled        = EXCLUDED.enabled,
                   config         = EXCLUDED.config,
                   handler_type   = EXCLUDED.handler_type,
                   config_schema  = EXCLUDED.config_schema,
                   updated_at     = now()
               RETURNING *""",
            workspace_id, skill.name, skill.description, skill.identity,
            json.dumps(skill.rules), json.dumps(skill.mcp_servers),
            json.dumps(skill.tags), skill.source, skill.source_version, skill.enabled,
            json.dumps(skill.config), skill.handler_type, json.dumps(skill.config_schema),
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

    # -- MIU-26: Usage logging and budget --

    async def log_usage(
        self,
        workspace_id: str,
        session_id: str | None,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        cost_usd: float,
    ) -> None:
        """Insert usage_logs row and atomically increment spend_current."""
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """INSERT INTO usage_logs
                           (workspace_id, session_id, model, prompt_tokens,
                            completion_tokens, total_tokens, cost_usd)
                       VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                    workspace_id, session_id, model,
                    prompt_tokens, completion_tokens, total_tokens, cost_usd,
                )
                await conn.execute(
                    """UPDATE workspaces
                       SET spend_current = spend_current + $2, updated_at = now()
                       WHERE id = $1""",
                    workspace_id, cost_usd,
                )

    async def check_budget(self, workspace_id: str) -> None:
        """No-op on PostgresBackend — caller checks via Workspace dataclass fields."""
        pass

    async def get_usage_summary(
        self, workspace_id: str, days: int = 30,
    ) -> dict[str, Any]:
        row = await self._pool.fetchrow(
            """SELECT
                   COUNT(*)          AS request_count,
                   SUM(total_tokens) AS total_tokens,
                   SUM(cost_usd)     AS total_cost_usd
               FROM usage_logs
               WHERE workspace_id = $1
                 AND created_at >= now() - ($2 || ' days')::interval""",
            workspace_id, str(days),
        )
        if not row:
            return {"request_count": 0, "total_tokens": 0, "total_cost_usd": 0.0}
        return {
            "request_count": row["request_count"] or 0,
            "total_tokens": row["total_tokens"] or 0,
            "total_cost_usd": float(row["total_cost_usd"] or 0),
        }

    async def reset_expired_budgets(self) -> int:
        """Reset spend_current=0 for workspaces whose budget_reset_at has passed."""
        result = await self._pool.execute(
            """UPDATE workspaces
               SET spend_current = 0,
                   budget_reset_at = now() + CAST(budget_duration AS interval),
                   updated_at = now()
               WHERE budget_reset_at IS NOT NULL
                 AND budget_reset_at <= now()"""
        )
        # asyncpg returns "UPDATE N"
        return int(result.split()[-1])

    # -- Row mappers --

    @staticmethod
    def _row_to_workspace(row: Any) -> Workspace:
        overrides = row["config_overrides"]
        if isinstance(overrides, str):
            overrides = json.loads(overrides)
        max_b = row.get("max_budget_usd")
        soft_b = row.get("soft_budget_usd")
        spend = row.get("spend_current")
        return Workspace(
            id=str(row["id"]), name=row["name"], identity=row["identity"],
            config_overrides=overrides or {},
            status=row["status"],
            created_at=row["created_at"], updated_at=row["updated_at"],
            max_budget_usd=float(max_b) if max_b is not None else None,
            soft_budget_usd=float(soft_b) if soft_b is not None else None,
            budget_duration=row.get("budget_duration") or "30d",
            budget_reset_at=row.get("budget_reset_at"),
            spend_current=float(spend) if spend is not None else 0.0,
        )

    @staticmethod
    def _row_to_session(row: Any) -> Session:
        meta = row["metadata"]
        if isinstance(meta, str):
            meta = json.loads(meta)
        return Session(
            id=str(row["id"]), workspace_id=str(row["workspace_id"]),
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
            id=str(row["id"]), session_id=str(row["session_id"]),
            role=row["role"], content=row["content"],
            metadata=meta or {},
            consolidated=row["consolidated"], created_at=row["created_at"],
        )

    @staticmethod
    def _row_to_memory(row: Any) -> Memory:
        src_sid = row.get("source_session_id")
        return Memory(
            id=str(row["id"]), workspace_id=str(row["workspace_id"]),
            category=row["category"], content=row["content"],
            source_session_id=str(src_sid) if src_sid else None,
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
            id=str(row["id"]), workspace_id=str(row["workspace_id"]),
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
            id=str(row["id"]), workspace_id=str(row["workspace_id"]),
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
        config = row.get("config") or {}
        if isinstance(config, str):
            config = json.loads(config)
        config_schema = row.get("config_schema") or {}
        if isinstance(config_schema, str):
            config_schema = json.loads(config_schema)
        return WorkspaceSkill(
            id=str(row["id"]), workspace_id=str(row["workspace_id"]),
            name=row["name"], description=row["description"],
            identity=row["identity"], rules=rules or [],
            mcp_servers=mcp or {}, tags=tags or [],
            source=row["source"], source_version=row["source_version"],
            enabled=row["enabled"],
            created_at=row["created_at"], updated_at=row["updated_at"],
            config=config,
            handler_type=row.get("handler_type") or "prompt",
            config_schema=config_schema,
        )
