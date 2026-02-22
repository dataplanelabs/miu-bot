"""asyncpg connection pool lifecycle management."""

from __future__ import annotations

from loguru import logger

try:
    import asyncpg
except ImportError:
    asyncpg = None  # type: ignore[assignment]


async def create_pool(
    dsn: str, min_size: int = 5, max_size: int = 20
) -> "asyncpg.Pool":
    """Create and return an asyncpg connection pool."""
    if asyncpg is None:
        raise ImportError("asyncpg is required for PostgreSQL backend: pip install asyncpg")

    async def _init_conn(conn: "asyncpg.Connection") -> None:
        try:
            from pgvector.asyncpg import register_vector
            await register_vector(conn)
        except ImportError:
            pass  # pgvector optional

    pool = await asyncpg.create_pool(
        dsn, min_size=min_size, max_size=max_size, init=_init_conn
    )
    logger.info(f"Connection pool created (min={min_size}, max={max_size})")
    return pool


async def close_pool(pool: "asyncpg.Pool") -> None:
    """Gracefully close the connection pool."""
    await pool.close()
    logger.info("Connection pool closed")


async def health_check(pool: "asyncpg.Pool") -> bool:
    """Check pool health with a simple query."""
    try:
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return True
    except Exception as e:
        logger.warning(f"Health check failed: {e}")
        return False
