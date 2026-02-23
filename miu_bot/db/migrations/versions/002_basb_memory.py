"""BASB 3-tier memory schema.

Revision ID: 002
Create Date: 2026-02-23
"""

from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Extend memories table with BASB tier fields
    op.execute("ALTER TABLE memories ADD COLUMN tier TEXT NOT NULL DEFAULT 'active'")
    op.execute("ALTER TABLE memories ADD COLUMN source_type TEXT")
    op.execute("ALTER TABLE memories ADD COLUMN priority INT NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE memories ADD COLUMN expires_at TIMESTAMPTZ")
    op.execute("""
        CREATE INDEX idx_memories_tier
        ON memories (workspace_id, tier)
    """)

    # Daily notes table
    op.execute("""
        CREATE TABLE daily_notes (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            date DATE NOT NULL,
            summary TEXT,
            key_topics JSONB DEFAULT '[]',
            decisions_made JSONB DEFAULT '[]',
            action_items JSONB DEFAULT '[]',
            emotional_tone TEXT,
            message_count INT NOT NULL DEFAULT 0,
            consolidated BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE(workspace_id, date)
        )
    """)

    # Consolidation log table
    op.execute("""
        CREATE TABLE consolidation_log (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id TEXT NOT NULL,
            type TEXT NOT NULL,
            period_start DATE,
            period_end DATE,
            input_count INT NOT NULL DEFAULT 0,
            output_count INT NOT NULL DEFAULT 0,
            model_used TEXT,
            tokens_used INT,
            cost_estimate DECIMAL(10,6),
            status TEXT NOT NULL DEFAULT 'pending',
            error TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE INDEX idx_consolidation_log_ws
        ON consolidation_log (workspace_id, type, created_at)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS consolidation_log")
    op.execute("DROP TABLE IF EXISTS daily_notes")
    op.execute("DROP INDEX IF EXISTS idx_memories_tier")
    op.execute("ALTER TABLE memories DROP COLUMN IF EXISTS tier")
    op.execute("ALTER TABLE memories DROP COLUMN IF EXISTS source_type")
    op.execute("ALTER TABLE memories DROP COLUMN IF EXISTS priority")
    op.execute("ALTER TABLE memories DROP COLUMN IF EXISTS expires_at")
