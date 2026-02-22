"""PostgreSQL backend implementation using asyncpg."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

_MUTABLE_COLUMNS = {"name", "identity", "config_overrides", "status"}

from miu_bot.db.backend import Memory, Message, Session, Workspace

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
    ) -> Memory:
        mem_id = str(uuid.uuid4())
        row = await self._pool.fetchrow(
            """INSERT INTO memories (id, workspace_id, category, content, source_session_id, created_at)
               VALUES ($1, $2, $3, $4, $5, $6)
               RETURNING *""",
            mem_id, workspace_id, category, content, source_session_id, datetime.now(timezone.utc),
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
        )
