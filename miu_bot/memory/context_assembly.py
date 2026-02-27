"""Tier-based memory context assembly for agent prompts."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from miu_bot.db.backend import Memory, MemoryBackend


def _deduplicate(memories: list["Memory"]) -> list["Memory"]:
    """Deduplicate memories by id, preserving order."""
    seen: set[str] = set()
    result: list[Memory] = []
    for m in memories:
        if m.id not in seen:
            seen.add(m.id)
            result.append(m)
    return result


async def assemble_memory_context(
    backend: "MemoryBackend",
    workspace_id: str,
    query: str | None = None,
    embedding_model: str | None = None,
) -> str:
    """Assemble memory context from BASB tiers.

    - Tier 1 (Active): always included
    - Tier 2 (Reference): semantic search when embedding_model provided, else keyword match
    - Tier 3 (Archive): not included by default
    """
    parts: list[str] = []

    # Active tier: always in context
    active = await backend.get_memories_by_tier(workspace_id, "active", limit=50)

    # Reference tier: semantic or keyword match when query available
    reference_relevant: list[Memory] = []
    if query and embedding_model and hasattr(backend, "search_memories_semantic"):
        # Hybrid: semantic top-K across all tiers + active tier, deduplicated
        try:
            semantic = await backend.search_memories_semantic(  # type: ignore[union-attr]
                workspace_id, query, limit=10, embedding_model=embedding_model,
            )
            combined = _deduplicate(semantic + active)
            if combined:
                combined_text = "\n".join(f"- {m.content}" for m in combined)
                parts.append(f"## Knowledge\n{combined_text}")
            return "\n\n".join(parts) if parts else ""
        except Exception:
            pass  # Fallback to keyword path below

    if active:
        active_text = "\n".join(f"- {m.content}" for m in active)
        parts.append(f"## Active Knowledge\n{active_text}")

    if query:
        reference = await backend.get_memories_by_tier(
            workspace_id, "reference", limit=20
        )
        keywords = set(query.lower().split())
        reference_relevant = [
            m for m in reference if any(kw in m.content.lower() for kw in keywords)
        ]
        if reference_relevant:
            ref_text = "\n".join(f"- {m.content}" for m in reference_relevant[:10])
            parts.append(f"## Reference Knowledge\n{ref_text}")

    return "\n\n".join(parts) if parts else ""
