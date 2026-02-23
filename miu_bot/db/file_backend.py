"""File-based backend wrapping existing SessionManager + MemoryStore."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger

from miu_bot.db.backend import Memory, Message, Session, Workspace
from miu_bot.utils.helpers import ensure_dir


class FileBackend:
    """MemoryBackend backed by filesystem (no Postgres required)."""

    def __init__(self, data_dir: Path | None = None):
        self._data_dir = data_dir or (Path.home() / ".miu-bot")
        self._workspaces_dir = ensure_dir(self._data_dir / "workspaces")
        self._sessions_dir = ensure_dir(self._data_dir / "sessions")
        self._session_cache: dict[str, Session] = {}

    async def initialize(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def health_check(self) -> bool:
        return self._data_dir.exists()

    # -- Workspace --

    def _ws_path(self, name: str) -> Path:
        return self._workspaces_dir / f"{name}.json"

    def _load_ws(self, path: Path) -> Workspace | None:
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return Workspace(
            id=data["id"], name=data["name"], identity=data.get("identity", ""),
            config_overrides=data.get("config_overrides", {}),
            status=data.get("status", "active"),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
        )

    def _save_ws(self, ws: Workspace) -> None:
        data = {
            "id": ws.id, "name": ws.name, "identity": ws.identity,
            "config_overrides": ws.config_overrides, "status": ws.status,
            "created_at": ws.created_at.isoformat(), "updated_at": ws.updated_at.isoformat(),
        }
        self._ws_path(ws.name).write_text(json.dumps(data, indent=2), encoding="utf-8")

    async def get_workspace(self, workspace_id: str) -> Workspace | None:
        for path in self._workspaces_dir.glob("*.json"):
            ws = self._load_ws(path)
            if ws and ws.id == workspace_id:
                return ws
        return None

    async def get_workspace_by_name(self, name: str) -> Workspace | None:
        return self._load_ws(self._ws_path(name))

    async def list_workspaces(self) -> list[Workspace]:
        result = []
        for path in sorted(self._workspaces_dir.glob("*.json")):
            ws = self._load_ws(path)
            if ws:
                result.append(ws)
        return result

    async def create_workspace(
        self, name: str, identity: str, config_overrides: dict[str, Any] | None = None
    ) -> Workspace:
        now = datetime.now(timezone.utc)
        ws = Workspace(
            id=str(uuid.uuid4()), name=name, identity=identity,
            config_overrides=config_overrides or {}, status="active",
            created_at=now, updated_at=now,
        )
        self._save_ws(ws)
        return ws

    _MUTABLE_FIELDS = {"name", "identity", "config_overrides", "status"}

    async def update_workspace(self, workspace_id: str, **kwargs: Any) -> Workspace | None:
        ws = await self.get_workspace(workspace_id)
        if not ws:
            return None
        for key, val in kwargs.items():
            if key not in self._MUTABLE_FIELDS:
                raise ValueError(f"Cannot update field: {key}")
            setattr(ws, key, val)
        ws.updated_at = datetime.now(timezone.utc)
        self._save_ws(ws)
        return ws

    async def delete_workspace(self, workspace_id: str) -> bool:
        for path in self._workspaces_dir.glob("*.json"):
            ws = self._load_ws(path)
            if ws and ws.id == workspace_id:
                path.unlink()
                return True
        return False

    # -- Session --

    def _session_path(self, session_id: str) -> Path:
        return self._sessions_dir / f"{session_id}.jsonl"

    async def get_or_create_session(
        self, workspace_id: str, channel: str, identifier: str
    ) -> Session:
        cache_key = f"{workspace_id}:{channel}:{identifier}"
        if cache_key in self._session_cache:
            return self._session_cache[cache_key]

        # Scan existing sessions for match
        for path in self._sessions_dir.glob("*.jsonl"):
            try:
                first_line = path.read_text(encoding="utf-8").split("\n", 1)[0]
                meta = json.loads(first_line)
                if (
                    meta.get("_type") == "session_meta"
                    and meta.get("workspace_id") == workspace_id
                    and meta.get("channel") == channel
                    and meta.get("channel_identifier") == identifier
                ):
                    sess = Session(
                        id=path.stem, workspace_id=workspace_id,
                        channel=channel, channel_identifier=identifier,
                        metadata=meta.get("metadata", {}),
                        last_consolidated_at=None, created_at=datetime.fromisoformat(meta["created_at"]),
                    )
                    self._session_cache[cache_key] = sess
                    return sess
            except Exception:
                continue

        sess_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        sess = Session(
            id=sess_id, workspace_id=workspace_id,
            channel=channel, channel_identifier=identifier,
            metadata={}, last_consolidated_at=None, created_at=now,
        )
        meta_line = json.dumps({
            "_type": "session_meta", "workspace_id": workspace_id,
            "channel": channel, "channel_identifier": identifier,
            "metadata": {}, "created_at": now.isoformat(),
        })
        self._session_path(sess_id).write_text(meta_line + "\n", encoding="utf-8")
        self._session_cache[cache_key] = sess
        return sess

    async def get_session(self, session_id: str) -> Session | None:
        path = self._session_path(session_id)
        if not path.exists():
            return None
        first_line = path.read_text(encoding="utf-8").split("\n", 1)[0]
        meta = json.loads(first_line)
        return Session(
            id=session_id, workspace_id=meta.get("workspace_id", ""),
            channel=meta.get("channel", ""), channel_identifier=meta.get("channel_identifier", ""),
            metadata=meta.get("metadata", {}), last_consolidated_at=None,
            created_at=datetime.fromisoformat(meta.get("created_at", datetime.now(timezone.utc).isoformat())),
        )

    # -- Messages --

    async def save_message(
        self, session_id: str, role: str, content: str, metadata: dict[str, Any] | None = None
    ) -> Message:
        path = self._session_path(session_id)
        msg_id = sum(1 for _ in path.read_text(encoding="utf-8").splitlines()) if path.exists() else 1
        now = datetime.now(timezone.utc)
        line = json.dumps({
            "id": msg_id, "role": role, "content": content,
            "metadata": metadata or {}, "consolidated": False,
            "created_at": now.isoformat(),
        })
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        return Message(
            id=msg_id, session_id=session_id, role=role, content=content,
            metadata=metadata or {}, consolidated=False, created_at=now,
        )

    async def get_messages(self, session_id: str, limit: int = 50) -> list[Message]:
        path = self._session_path(session_id)
        if not path.exists():
            return []
        messages: list[Message] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            data = json.loads(line)
            if data.get("_type"):
                continue  # skip metadata line
            messages.append(Message(
                id=data.get("id", 0), session_id=session_id,
                role=data["role"], content=data["content"],
                metadata=data.get("metadata", {}),
                consolidated=data.get("consolidated", False),
                created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(timezone.utc),
            ))
        return messages[-limit:]

    async def mark_consolidated(self, session_id: str, up_to_id: int) -> int:
        # File backend: not fully supported, just return 0
        logger.debug(f"FileBackend.mark_consolidated: no-op for session {session_id}")
        return 0

    # -- Memories --

    def _memories_dir(self, workspace_id: str) -> Path:
        return ensure_dir(self._data_dir / "memories" / workspace_id)

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
        mem_dir = self._memories_dir(workspace_id)
        entry = json.dumps({
            "id": mem_id, "workspace_id": workspace_id, "category": category,
            "content": content, "source_session_id": source_session_id,
            "created_at": now.isoformat(),
        })
        with open(mem_dir / "memories.jsonl", "a", encoding="utf-8") as f:
            f.write(entry + "\n")
        return Memory(
            id=mem_id, workspace_id=workspace_id, category=category,
            content=content, source_session_id=source_session_id, created_at=now,
        )

    async def get_memories(
        self, workspace_id: str, categories: list[str] | None = None
    ) -> list[Memory]:
        path = self._memories_dir(workspace_id) / "memories.jsonl"
        if not path.exists():
            return []
        result = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            data = json.loads(line)
            if categories and data.get("category") not in categories:
                continue
            result.append(Memory(
                id=data["id"], workspace_id=data["workspace_id"],
                category=data["category"], content=data["content"],
                source_session_id=data.get("source_session_id"),
                created_at=datetime.fromisoformat(data["created_at"]),
            ))
        return result

    async def replace_memories(
        self, workspace_id: str, category: str, content: str
    ) -> None:
        path = self._memories_dir(workspace_id) / "memories.jsonl"
        kept: list[str] = []
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                data = json.loads(line)
                if data.get("category") != category:
                    kept.append(line)
        # Add replacement
        now = datetime.now(timezone.utc)
        entry = json.dumps({
            "id": str(uuid.uuid4()), "workspace_id": workspace_id,
            "category": category, "content": content,
            "source_session_id": None, "created_at": now.isoformat(),
        })
        kept.append(entry)
        path.write_text("\n".join(kept) + "\n", encoding="utf-8")

    # -- BASB tier stubs (file backend doesn't support tiered memory) --

    async def get_memories_by_tier(
        self, workspace_id: str, tier: str, limit: int = 50
    ) -> list["Memory"]:
        # File backend treats all memories as active tier
        all_mems = await self.get_memories(workspace_id)
        return all_mems[:limit]

    async def save_daily_note(self, note: Any) -> Any:
        return note  # no-op for file backend

    async def get_daily_notes(
        self, workspace_id: str, start_date: Any, end_date: Any
    ) -> list:
        return []

    async def log_consolidation(self, entry: Any) -> None:
        pass  # no-op for file backend

    async def get_unconsolidated_messages(
        self, workspace_id: str, since: Any, until: Any
    ) -> list["Message"]:
        return []

    async def get_unconsolidated_daily_notes(
        self, workspace_id: str, start: Any, end: Any
    ) -> list:
        return []

    async def mark_daily_notes_consolidated(
        self, workspace_id: str, note_ids: list[str]
    ) -> None:
        pass

    async def promote_memory_tier(
        self, memory_id: str, new_tier: str, source_type: str | None = None
    ) -> None:
        pass

    async def delete_expired_memories(
        self, workspace_id: str, tier: str, older_than: Any
    ) -> int:
        return 0

    async def delete_old_daily_notes(
        self, workspace_id: str, older_than: Any
    ) -> int:
        return 0
