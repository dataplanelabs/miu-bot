"""Embedding generation and pgvector search helpers for semantic memory retrieval."""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

EMBED_MODEL_DEFAULT = "text-embedding-3-small"
EMBED_DIMS = 1536


async def generate_embedding(
    text: str,
    model: str = EMBED_MODEL_DEFAULT,
) -> list[float] | None:
    """Generate text embedding via LiteLLM aembedding().

    Returns None on any failure — callers must handle graceful degradation.
    """
    try:
        import litellm
        response = await litellm.aembedding(model=model, input=[text])
        return response.data[0]["embedding"]
    except Exception as exc:
        logger.warning("Embedding generation failed (model=%s): %s", model, exc)
        return None


async def vector_search(
    pool: object,
    workspace_id: str,
    embedding: list[float],
    category: str | None = None,
    limit: int = 10,
) -> list:
    """Cosine similarity search in memories table.

    Uses optional category pre-filter (Pattern C from research).
    Returns asyncpg Record list; callers map with _row_to_memory().
    """
    vec_str = json.dumps(embedding)
    if category:
        rows = await pool.fetch(  # type: ignore[union-attr]
            """SELECT id, workspace_id, category, content, source_session_id,
                      tier, source_type, priority, expires_at, created_at,
                      embedding <=> $2::vector AS distance
               FROM memories
               WHERE workspace_id = $1
                 AND category = $3
                 AND embedding IS NOT NULL
               ORDER BY distance
               LIMIT $4""",
            workspace_id, vec_str, category, limit,
        )
    else:
        rows = await pool.fetch(  # type: ignore[union-attr]
            """SELECT id, workspace_id, category, content, source_session_id,
                      tier, source_type, priority, expires_at, created_at,
                      embedding <=> $2::vector AS distance
               FROM memories
               WHERE workspace_id = $1
                 AND embedding IS NOT NULL
               ORDER BY distance
               LIMIT $3""",
            workspace_id, vec_str, limit,
        )
    return list(rows)


async def backfill_null_embeddings(
    pool: object,
    model: str = EMBED_MODEL_DEFAULT,
    batch: int = 100,
) -> int:
    """Backfill memories with NULL embedding. Returns count updated. Run at startup."""
    rows = await pool.fetch(  # type: ignore[union-attr]
        "SELECT id, content FROM memories WHERE embedding IS NULL LIMIT $1", batch
    )
    updated = 0
    for row in rows:
        vec = await generate_embedding(row["content"], model)
        if vec:
            await pool.execute(  # type: ignore[union-attr]
                "UPDATE memories SET embedding = $1::vector WHERE id = $2",
                json.dumps(vec), row["id"],
            )
            updated += 1
    return updated
