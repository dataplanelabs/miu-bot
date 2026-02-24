"""BASB weekly memory consolidation."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any, TYPE_CHECKING

import json_repair
from loguru import logger

if TYPE_CHECKING:
    from miu_bot.db.backend import MemoryBackend
    from miu_bot.providers.base import LLMProvider

from miu_bot.memory.prompts import WEEKLY_CONSOLIDATION_PROMPT


class WeeklyConsolidation:
    """Compress daily notes -> Reference tier memories."""

    def __init__(self, backend: "MemoryBackend", pool: Any):
        self.backend = backend
        self._pool = pool

    async def run_for_workspace(
        self,
        workspace_id: str,
        provider: "LLMProvider",
        model: str,
    ) -> dict[str, Any]:
        """Run weekly consolidation for a single workspace."""
        ws = await self.backend.get_workspace(workspace_id)
        if not ws or ws.status != "active":
            return {"status": "skipped", "reason": "workspace_inactive"}

        lock_key = int.from_bytes(
            hashlib.sha256(f"weekly:{ws.id}".encode()).digest()[:8],
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
                logger.error(f"Weekly consolidation failed for {ws.name}: {e}")
                return {"status": "error", "error": str(e)}
            finally:
                await conn.execute(
                    "SELECT pg_advisory_unlock($1)", lock_key
                )

    async def _process_workspace(
        self, ws: Any, provider: "LLMProvider", model: str
    ) -> dict[str, Any]:
        """Consolidate one workspace's daily notes from the past week."""
        now = datetime.now(timezone.utc)
        week_end = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = week_end - timedelta(days=7)

        notes = await self.backend.get_unconsolidated_daily_notes(
            ws.id, week_start, week_end
        )
        if len(notes) < 3:
            logger.debug(
                f"Skipping weekly for {ws.name}: only {len(notes)} daily notes"
            )
            return {"status": "skipped", "reason": "insufficient_notes"}

        active = await self.backend.get_memories_by_tier(ws.id, "active")
        notes_text = "\n\n".join(
            f"### {n.date}\n{n.summary}\nTopics: {', '.join(n.key_topics)}"
            for n in notes
        )
        active_text = "\n".join(
            f"[{m.id}] {m.content}" for m in active
        )

        prompt = WEEKLY_CONSOLIDATION_PROMPT.format(
            workspace_name=ws.name,
            week_start=week_start.date().isoformat(),
            week_end=week_end.date().isoformat(),
            daily_notes=notes_text,
            active_memories=active_text or "(none)",
        )

        response = await provider.chat(
            messages=[
                {
                    "role": "system",
                    "content": "Memory consolidation agent. JSON only.",
                },
                {"role": "user", "content": prompt},
            ],
            model=model,
        )

        text = (response.content or "").strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        result = json_repair.loads(text)
        if not isinstance(result, dict):
            raise ValueError(
                f"LLM returned non-dict response ({type(result).__name__}): "
                f"{str(result)[:200]}"
            )

        # Save weekly insight as Reference memory
        if insight := result.get("weekly_insight"):
            await self.backend.save_memory(
                workspace_id=ws.id,
                category="weekly_insight",
                content=insight,
                tier="reference",
                source_type="weekly_insight",
            )

        # Promote stable knowledge to Reference
        promoted = result.get("promote_to_reference", [])
        for item in promoted:
            await self.backend.save_memory(
                workspace_id=ws.id,
                category=item.get("category", "fact"),
                content=item["content"],
                tier="reference",
                source_type="weekly_insight",
            )

        # Demote stale Active memories (IDs from LLM may be hallucinated)
        for mem_id in result.get("demote_from_active", []):
            try:
                await self.backend.promote_memory_tier(mem_id, "archive")
            except Exception as e:
                logger.warning(f"Failed to demote memory {mem_id}: {e}")

        # Mark daily notes as consolidated
        note_ids = [n.id for n in notes]
        await self.backend.mark_daily_notes_consolidated(ws.id, note_ids)

        # Log consolidation
        tokens = response.usage.get("total_tokens", 0) if response.usage else 0
        from miu_bot.db.backend import ConsolidationLogEntry

        await self.backend.log_consolidation(
            ConsolidationLogEntry(
                id="",
                workspace_id=ws.id,
                type="weekly",
                period_start=week_start,
                period_end=week_end,
                input_count=len(notes),
                output_count=len(promoted),
                model_used=model,
                tokens_used=tokens,
                cost_estimate=None,
                status="completed",
                error=None,
                created_at=now,
            )
        )

        logger.info(
            f"Weekly consolidation for {ws.name}: "
            f"{len(notes)} notes -> {len(promoted)} promoted"
        )
        return {
            "status": "completed",
            "notes_processed": len(notes),
            "promoted": len(promoted),
        }
