"""BASB daily memory consolidation."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, TYPE_CHECKING

import json_repair
from loguru import logger

if TYPE_CHECKING:
    from miu_bot.db.backend import MemoryBackend
    from miu_bot.providers.base import LLMProvider

from miu_bot.memory.prompts import DAILY_CONSOLIDATION_PROMPT


class DailyConsolidation:
    """Process yesterday's messages into daily notes + Active memories."""

    def __init__(self, backend: "MemoryBackend", pool: Any):
        self.backend = backend
        self._pool = pool

    async def run_for_workspace(
        self,
        workspace_id: str,
        provider: "LLMProvider",
        model: str,
    ) -> dict[str, Any]:
        """Run daily consolidation for a single workspace.

        Returns result dict with status and counts.
        """
        ws = await self.backend.get_workspace(workspace_id)
        if not ws or ws.status != "active":
            return {"status": "skipped", "reason": "workspace_inactive"}

        # Distributed lock: only one worker processes each workspace
        lock_key = int.from_bytes(
            hashlib.sha256(f"daily:{ws.id}".encode()).digest()[:8],
            "big",
            signed=True,
        )

        async with self._pool.acquire() as conn:
            locked = await conn.fetchval(
                "SELECT pg_try_advisory_lock($1)", lock_key
            )
            if not locked:
                return {"status": "skipped", "reason": "locked"}

            try:
                return await self._process_workspace(ws, provider, model)
            except Exception as e:
                logger.error(f"Daily consolidation failed for {ws.name}: {e}")
                return {"status": "error", "error": str(e)}
            finally:
                await conn.execute(
                    "SELECT pg_advisory_unlock($1)", lock_key
                )

    async def _process_workspace(
        self, ws: Any, provider: "LLMProvider", model: str
    ) -> dict[str, Any]:
        """Consolidate one workspace's messages from yesterday."""
        now = datetime.now(timezone.utc)
        yesterday_start = (now - timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        yesterday_end = yesterday_start + timedelta(days=1)

        # Check idempotency: skip if already consolidated
        existing = await self.backend.get_daily_notes(
            ws.id, yesterday_start, yesterday_end
        )
        if existing:
            logger.debug(
                f"Daily note already exists for {ws.name} on {yesterday_start.date()}"
            )
            return {"status": "skipped", "reason": "already_consolidated"}

        # Get unconsolidated messages
        messages = await self.backend.get_unconsolidated_messages(
            ws.id, yesterday_start, yesterday_end
        )
        if not messages:
            return {"status": "skipped", "reason": "no_messages"}

        # Get current active memories for context
        active_memories = await self.backend.get_memories_by_tier(ws.id, "active")
        memories_text = "\n".join(
            f"[{m.id[:8]}] {m.content}" for m in active_memories
        )

        # Format conversations
        conv_lines = []
        for m in messages:
            conv_lines.append(
                f"[{m.created_at.strftime('%H:%M')}] {m.role}: {m.content[:500]}"
            )
        conversations = "\n".join(conv_lines)

        # LLM call
        prompt = DAILY_CONSOLIDATION_PROMPT.format(
            workspace_name=ws.name,
            date=yesterday_start.date().isoformat(),
            message_count=len(messages),
            current_memories=memories_text or "(none)",
            conversations=conversations,
        )

        response = await provider.chat(
            messages=[
                {
                    "role": "system",
                    "content": "You are a memory consolidation agent. Respond only with valid JSON.",
                },
                {"role": "user", "content": prompt},
            ],
            model=model,
        )

        # Parse response
        text = (response.content or "").strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        result = json_repair.loads(text)

        # Save daily note
        from miu_bot.db.backend import DailyNote

        note = DailyNote(
            id="",
            workspace_id=ws.id,
            date=yesterday_start,
            summary=result.get("daily_summary"),
            key_topics=result.get("key_topics", []),
            decisions_made=result.get("decisions_made", []),
            action_items=result.get("action_items", []),
            emotional_tone=result.get("emotional_tone"),
            message_count=len(messages),
            consolidated=False,
            created_at=now,
        )
        await self.backend.save_daily_note(note)

        # Save new Active-tier memories
        new_facts = result.get("new_facts", [])
        for fact in new_facts:
            await self.backend.save_memory(
                workspace_id=ws.id,
                category=fact.get("category", "fact"),
                content=fact["content"],
                tier="active",
                source_type="daily_note",
                priority=fact.get("priority", 0),
            )

        # Mark messages as consolidated (per-session)
        session_ids = {m.session_id for m in messages}
        for sid in session_ids:
            session_msgs = [m for m in messages if m.session_id == sid]
            if session_msgs:
                await self.backend.mark_consolidated(
                    sid, session_msgs[-1].id
                )

        # Log consolidation
        tokens = response.usage.get("total_tokens", 0) if response.usage else 0
        from miu_bot.db.backend import ConsolidationLogEntry

        await self.backend.log_consolidation(
            ConsolidationLogEntry(
                id="",
                workspace_id=ws.id,
                type="daily",
                period_start=yesterday_start,
                period_end=yesterday_end,
                input_count=len(messages),
                output_count=len(new_facts),
                model_used=model,
                tokens_used=tokens,
                cost_estimate=None,
                status="completed",
                error=None,
                created_at=now,
            )
        )

        logger.info(
            f"Daily consolidation for {ws.name}: "
            f"{len(messages)} msgs -> {len(new_facts)} facts"
        )
        return {
            "status": "completed",
            "messages_processed": len(messages),
            "facts_extracted": len(new_facts),
        }
