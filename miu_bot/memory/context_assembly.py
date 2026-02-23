"""Tier-based memory context assembly for agent prompts."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from miu_bot.db.backend import MemoryBackend


async def assemble_memory_context(
    backend: "MemoryBackend",
    workspace_id: str,
    query: str | None = None,
) -> str:
    """Assemble memory context from BASB tiers.

    - Tier 1 (Active): always included
    - Tier 2 (Reference): included if query provided (keyword match)
    - Tier 3 (Archive): not included by default
    """
    parts: list[str] = []

    # Active tier: always in context
    active = await backend.get_memories_by_tier(workspace_id, "active", limit=50)
    if active:
        active_text = "\n".join(f"- {m.content}" for m in active)
        parts.append(f"## Active Knowledge\n{active_text}")

    # Reference tier: on relevance (simple keyword match for now)
    if query:
        reference = await backend.get_memories_by_tier(
            workspace_id, "reference", limit=20
        )
        keywords = set(query.lower().split())
        relevant = [
            m for m in reference if any(kw in m.content.lower() for kw in keywords)
        ]
        if relevant:
            ref_text = "\n".join(f"- {m.content}" for m in relevant[:10])
            parts.append(f"## Reference Knowledge\n{ref_text}")

    return "\n\n".join(parts) if parts else ""
