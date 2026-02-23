"""BASB monthly deep consolidation."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any, TYPE_CHECKING

import json_repair
from loguru import logger

if TYPE_CHECKING:
    from miu_bot.db.backend import MemoryBackend
    from miu_bot.providers.base import LLMProvider

from miu_bot.memory.prompts import MONTHLY_CONSOLIDATION_PROMPT


class MonthlyConsolidation:
    """Deep consolidation: Reference -> Archive + monthly summary."""

    def __init__(self, backend: "MemoryBackend", pool: Any):
        self.backend = backend
        self._pool = pool

    async def run_for_workspace(
        self,
        workspace_id: str,
        provider: "LLMProvider",
        model: str,
    ) -> dict[str, Any]:
        """Run monthly consolidation for a single workspace."""
        ws = await self.backend.get_workspace(workspace_id)
        if not ws or ws.status != "active":
            return {"status": "skipped", "reason": "workspace_inactive"}

        lock_key = int.from_bytes(
            hashlib.sha256(f"monthly:{ws.id}".encode()).digest()[:8],
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
                logger.error(f"Monthly consolidation failed for {ws.name}: {e}")
                return {"status": "error", "error": str(e)}
            finally:
                await conn.execute(
                    "SELECT pg_advisory_unlock($1)", lock_key
                )

    async def _process_workspace(
        self, ws: Any, provider: "LLMProvider", model: str
    ) -> dict[str, Any]:
        """Deep consolidation for one workspace."""
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        prev_month_start = (month_start - timedelta(days=1)).replace(day=1)

        # Load weekly insights from past month
        reference = await self.backend.get_memories_by_tier(
            ws.id, "reference", limit=50
        )
        weekly_insights = [
            m
            for m in reference
            if m.source_type == "weekly_insight"
            and m.created_at >= prev_month_start
            and m.created_at < month_start
        ]

        if not weekly_insights:
            return {"status": "skipped", "reason": "no_weekly_insights"}

        insights_text = "\n\n".join(
            f"[{m.created_at.date()}] {m.content}" for m in weekly_insights
        )
        ref_text = "\n".join(
            f"[{m.id[:8]}] {m.content}"
            for m in reference
            if m.source_type != "weekly_insight"
        )

        prompt = MONTHLY_CONSOLIDATION_PROMPT.format(
            workspace_name=ws.name,
            month=prev_month_start.strftime("%B %Y"),
            weekly_insights=insights_text,
            reference_memories=ref_text or "(none)",
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

        # Save monthly summary as Archive memory
        if summary := result.get("monthly_summary"):
            await self.backend.save_memory(
                workspace_id=ws.id,
                category="monthly_summary",
                content=summary,
                tier="archive",
                source_type="monthly_summary",
            )

        # Archive old Reference memories
        for mem_id in result.get("archive_from_reference", []):
            await self.backend.promote_memory_tier(
                mem_id, "archive", "monthly_summary"
            )

        # Prune contradictions
        for item in result.get("prune_contradictions", []):
            await self.backend.promote_memory_tier(item["memory_id"], "archive")

        # Housekeeping: delete old Archive (>90d) and old daily_notes (>60d)
        cutoff_archive = now - timedelta(days=90)
        cutoff_notes = now - timedelta(days=60)
        deleted_archive = await self.backend.delete_expired_memories(
            ws.id, "archive", cutoff_archive
        )
        deleted_notes = await self.backend.delete_old_daily_notes(
            ws.id, cutoff_notes
        )

        # Log consolidation
        tokens = response.usage.get("total_tokens", 0) if response.usage else 0
        from miu_bot.db.backend import ConsolidationLogEntry

        await self.backend.log_consolidation(
            ConsolidationLogEntry(
                id="",
                workspace_id=ws.id,
                type="monthly",
                period_start=prev_month_start,
                period_end=month_start,
                input_count=len(weekly_insights),
                output_count=len(result.get("key_knowledge", [])),
                model_used=model,
                tokens_used=tokens,
                cost_estimate=None,
                status="completed",
                error=None,
                created_at=now,
            )
        )

        logger.info(
            f"Monthly consolidation for {ws.name}: "
            f"{len(weekly_insights)} insights, "
            f"archived={deleted_archive}, pruned_notes={deleted_notes}"
        )
        return {
            "status": "completed",
            "insights_processed": len(weekly_insights),
            "archived": deleted_archive,
            "notes_pruned": deleted_notes,
        }
