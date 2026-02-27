"""Add HNSW index on memories.embedding for fast cosine similarity search.

Revision ID: 007
Create Date: 2026-02-27
"""

from alembic import op

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # HNSW: better than IVFFlat for small datasets + frequent inserts + empty-index creation
    # m=16, ef_construction=64 are langchain-postgres defaults; good for <1M rows
    # NOTE: CONCURRENTLY not used — Alembic runs in a transaction; non-CONCURRENT is instant at <1K rows
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_memories_embedding_hnsw
        ON memories
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_memories_embedding_hnsw")
