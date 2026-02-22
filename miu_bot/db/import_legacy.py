"""Legacy data importer: file-based storage -> MemoryBackend."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

from miu_bot.db.backend import MemoryBackend


@dataclass
class ImportResult:
    workspace_name: str = ""
    sessions_imported: int = 0
    messages_imported: int = 0
    memories_imported: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


class LegacyImporter:
    """Import legacy file-based data into a MemoryBackend."""

    def __init__(self, backend: MemoryBackend, data_dir: Path):
        self.backend = backend
        self.data_dir = data_dir  # ~/.miu-bot/

    async def import_all(self, dry_run: bool = False) -> ImportResult:
        result = ImportResult()

        # 1. Create default workspace from bootstrap files
        workspace = await self._import_workspace(result, dry_run)
        if not workspace:
            result.errors.append("Failed to create/find default workspace")
            return result

        workspace_id = workspace.id
        result.workspace_name = workspace.name

        # 2. Import sessions and messages
        await self._import_sessions(workspace_id, result, dry_run)

        # 3. Import memories
        await self._import_memories(workspace_id, result, dry_run)

        return result

    async def _import_workspace(self, result: ImportResult, dry_run: bool):
        """Create default workspace from bootstrap files (AGENTS.md, SOUL.md, USER.md)."""
        # Check if default workspace already exists
        existing = await self.backend.get_workspace_by_name("default")
        if existing:
            logger.info("Workspace 'default' already exists, skipping creation")
            result.skipped += 1
            return existing

        # Read bootstrap files
        ws_dir = self.data_dir / "workspace"
        identity_parts = []

        for filename, section in [
            ("AGENTS.md", "Identity"),
            ("SOUL.md", "Soul"),
            ("USER.md", "Context"),
        ]:
            path = ws_dir / filename
            if path.exists():
                content = path.read_text(encoding="utf-8").strip()
                if content:
                    identity_parts.append(f"## {section}\n\n{content}")

        identity = "---\nname: default\nversion: '1.0'\nlanguage: en\n---\n\n"
        identity += "\n\n".join(identity_parts) if identity_parts else ""

        if dry_run:
            logger.info(f"[dry-run] Would create workspace 'default' with {len(identity_parts)} identity sections")
            # Return a stub for downstream steps
            from miu_bot.db.backend import Workspace
            from datetime import datetime, timezone
            return Workspace(
                id="dry-run", name="default", identity=identity,
                config_overrides={}, status="active",
                created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
            )

        return await self.backend.create_workspace("default", identity)

    async def _import_sessions(self, workspace_id: str, result: ImportResult, dry_run: bool):
        """Import JSONL session files into backend."""
        sessions_dir = self.data_dir / "sessions"
        if not sessions_dir.exists():
            logger.info("No sessions directory found, skipping")
            return

        for jsonl_path in sorted(sessions_dir.glob("*.jsonl")):
            try:
                await self._import_single_session(workspace_id, jsonl_path, result, dry_run)
            except Exception as e:
                result.errors.append(f"{jsonl_path.name}: {e}")
                logger.warning(f"Error importing {jsonl_path.name}: {e}")

    async def _import_single_session(
        self, workspace_id: str, jsonl_path: Path, result: ImportResult, dry_run: bool
    ):
        """Import a single JSONL session file."""
        # Parse filename: telegram_12345.jsonl -> channel=telegram, identifier=12345
        stem = jsonl_path.stem  # e.g. "telegram_12345" or "cli_direct"
        # Use rsplit to handle channel names with underscores
        parts = stem.rsplit("_", 1)
        if len(parts) == 2:
            channel, identifier = parts
        else:
            channel, identifier = stem, "unknown"

        lines = jsonl_path.read_text(encoding="utf-8").splitlines()
        messages = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                result.errors.append(f"{jsonl_path.name}: malformed JSON line")
                continue

            # Skip metadata line
            if data.get("_type") in ("metadata", "session_meta"):
                continue

            role = data.get("role", "user")
            content = data.get("content", "")
            if not content:
                continue
            messages.append({"role": role, "content": content, "metadata": {}})

        if not messages:
            result.skipped += 1
            return

        if dry_run:
            logger.info(f"[dry-run] Would import session {channel}:{identifier} with {len(messages)} messages")
            result.sessions_imported += 1
            result.messages_imported += len(messages)
            return

        # Create session
        session = await self.backend.get_or_create_session(workspace_id, channel, identifier)

        # Check if session already has messages (idempotency)
        existing = await self.backend.get_messages(session.id, limit=1)
        if existing:
            logger.info(f"Session {channel}:{identifier} already has messages, skipping")
            result.skipped += 1
            return

        # Import messages
        for msg in messages:
            await self.backend.save_message(session.id, msg["role"], msg["content"], msg["metadata"])

        result.sessions_imported += 1
        result.messages_imported += len(messages)

    async def _import_memories(self, workspace_id: str, result: ImportResult, dry_run: bool):
        """Import MEMORY.md and HISTORY.md into memories table."""
        ws_dir = self.data_dir / "workspace"
        memory_dir = ws_dir / "memory"

        # Import MEMORY.md as "fact"
        memory_path = memory_dir / "MEMORY.md"
        if memory_path.exists():
            content = memory_path.read_text(encoding="utf-8").strip()
            if content:
                if dry_run:
                    logger.info(f"[dry-run] Would import MEMORY.md as 'fact' ({len(content)} chars)")
                else:
                    await self.backend.save_memory(workspace_id, "fact", content)
                result.memories_imported += 1

        # Import HISTORY.md as "event" entries (split by double newline)
        history_path = memory_dir / "HISTORY.md"
        if history_path.exists():
            content = history_path.read_text(encoding="utf-8").strip()
            if content:
                paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
                for paragraph in paragraphs:
                    if dry_run:
                        logger.info(f"[dry-run] Would import event: {paragraph[:60]}...")
                    else:
                        await self.backend.save_memory(workspace_id, "event", paragraph)
                    result.memories_imported += 1
