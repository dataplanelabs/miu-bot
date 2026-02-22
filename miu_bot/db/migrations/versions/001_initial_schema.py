"""Initial multi-tenant schema.

Revision ID: 001
Create Date: 2026-02-22
"""

from alembic import op

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\"")
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.execute("""
        CREATE TABLE workspaces (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            identity TEXT NOT NULL DEFAULT '',
            config_overrides JSONB NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'active',
            created_at TIMESTAMP NOT NULL DEFAULT now(),
            updated_at TIMESTAMP NOT NULL DEFAULT now()
        )
    """)

    op.execute("""
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY,
            workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            channel TEXT NOT NULL,
            channel_identifier TEXT NOT NULL,
            metadata JSONB NOT NULL DEFAULT '{}',
            last_consolidated_at TIMESTAMP,
            created_at TIMESTAMP NOT NULL DEFAULT now(),
            UNIQUE (workspace_id, channel, channel_identifier)
        )
    """)
    op.execute("CREATE INDEX idx_sessions_workspace ON sessions(workspace_id)")

    op.execute("""
        CREATE TABLE messages (
            id SERIAL PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            role TEXT NOT NULL,
            content TEXT NOT NULL DEFAULT '',
            metadata JSONB NOT NULL DEFAULT '{}',
            consolidated BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMP NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX idx_messages_session ON messages(session_id, created_at)")
    op.execute(
        "CREATE INDEX idx_messages_unconsolidated ON messages(session_id) WHERE consolidated = FALSE"
    )

    op.execute("""
        CREATE TABLE memories (
            id TEXT PRIMARY KEY,
            workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            category TEXT NOT NULL,
            content TEXT NOT NULL DEFAULT '',
            embedding vector(1536),
            source_session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
            created_at TIMESTAMP NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX idx_memories_workspace ON memories(workspace_id, category)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS memories CASCADE")
    op.execute("DROP TABLE IF EXISTS messages CASCADE")
    op.execute("DROP TABLE IF EXISTS sessions CASCADE")
    op.execute("DROP TABLE IF EXISTS workspaces CASCADE")
