"""Schema V2: UUIDv7 everywhere — native PG 18.

Drop all tables and recreate with uuid PK + DEFAULT uuidv7().
Data loss acceptable (<300 rows, early stage).

Revision ID: 005
Create Date: 2026-02-24
"""

from alembic import op

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Ensure vector extension exists (for pgvector)
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Drop all tables (order respects FK dependencies via CASCADE)
    op.execute("""
        DROP TABLE IF EXISTS
            consolidation_log,
            daily_notes,
            memories,
            messages,
            workspace_templates,
            workspace_skills,
            sessions,
            workspaces
        CASCADE
    """)

    # Skip DROP EXTENSION uuid-ossp — requires superuser; harmless to leave

    # -- Recreate tables in FK order --

    op.execute("""
        CREATE TABLE workspaces (
            id              uuid PRIMARY KEY DEFAULT uuidv7(),
            name            text NOT NULL UNIQUE,
            identity        text NOT NULL DEFAULT '',
            config_overrides jsonb NOT NULL DEFAULT '{}',
            status          text NOT NULL DEFAULT 'active',
            created_at      timestamptz NOT NULL DEFAULT now(),
            updated_at      timestamptz NOT NULL DEFAULT now()
        )
    """)

    op.execute("""
        CREATE TABLE sessions (
            id                    uuid PRIMARY KEY DEFAULT uuidv7(),
            workspace_id          uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            channel               text NOT NULL,
            channel_identifier    text NOT NULL,
            metadata              jsonb NOT NULL DEFAULT '{}',
            last_consolidated_at  timestamptz,
            created_at            timestamptz NOT NULL DEFAULT now(),

            UNIQUE (workspace_id, channel, channel_identifier)
        )
    """)
    op.execute("CREATE INDEX idx_sessions_workspace ON sessions(workspace_id)")

    op.execute("""
        CREATE TABLE messages (
            id            uuid PRIMARY KEY DEFAULT uuidv7(),
            session_id    uuid NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            role          text NOT NULL,
            content       text NOT NULL DEFAULT '',
            metadata      jsonb NOT NULL DEFAULT '{}',
            consolidated  boolean NOT NULL DEFAULT false,
            created_at    timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX idx_messages_session_created ON messages(session_id, created_at)"
    )
    op.execute(
        "CREATE INDEX idx_messages_unconsolidated ON messages(session_id) "
        "WHERE consolidated = false"
    )

    op.execute("""
        CREATE TABLE memories (
            id                uuid PRIMARY KEY DEFAULT uuidv7(),
            workspace_id      uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            category          text NOT NULL,
            content           text NOT NULL DEFAULT '',
            embedding         vector(1536),
            source_session_id uuid REFERENCES sessions(id) ON DELETE SET NULL,
            tier              text NOT NULL DEFAULT 'active',
            source_type       text,
            priority          integer NOT NULL DEFAULT 0,
            expires_at        timestamptz,
            created_at        timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX idx_memories_workspace_category ON memories(workspace_id, category)"
    )
    op.execute(
        "CREATE INDEX idx_memories_workspace_tier ON memories(workspace_id, tier)"
    )
    op.execute(
        "CREATE INDEX idx_memories_expires ON memories(expires_at) "
        "WHERE expires_at IS NOT NULL"
    )

    op.execute("""
        CREATE TABLE daily_notes (
            id              uuid PRIMARY KEY DEFAULT uuidv7(),
            workspace_id    uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            date            date NOT NULL,
            summary         text,
            key_topics      jsonb NOT NULL DEFAULT '[]',
            decisions_made  jsonb NOT NULL DEFAULT '[]',
            action_items    jsonb NOT NULL DEFAULT '[]',
            emotional_tone  text,
            message_count   integer NOT NULL DEFAULT 0,
            consolidated    boolean NOT NULL DEFAULT false,
            created_at      timestamptz NOT NULL DEFAULT now(),

            UNIQUE (workspace_id, date)
        )
    """)

    op.execute("""
        CREATE TABLE consolidation_log (
            id              uuid PRIMARY KEY DEFAULT uuidv7(),
            workspace_id    uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            type            text NOT NULL,
            period_start    date,
            period_end      date,
            input_count     integer NOT NULL DEFAULT 0,
            output_count    integer NOT NULL DEFAULT 0,
            model_used      text,
            tokens_used     integer,
            cost_estimate   numeric,
            status          text NOT NULL DEFAULT 'pending',
            error           text,
            created_at      timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX idx_consolidation_workspace_type "
        "ON consolidation_log(workspace_id, type, created_at)"
    )

    op.execute("""
        CREATE TABLE workspace_templates (
            id              uuid PRIMARY KEY DEFAULT uuidv7(),
            workspace_id    uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            template_type   text NOT NULL,
            content         text NOT NULL DEFAULT '',
            config          jsonb NOT NULL DEFAULT '{}',
            created_at      timestamptz NOT NULL DEFAULT now(),
            updated_at      timestamptz NOT NULL DEFAULT now(),

            UNIQUE (workspace_id, template_type)
        )
    """)

    op.execute("""
        CREATE TABLE workspace_skills (
            id              uuid PRIMARY KEY DEFAULT uuidv7(),
            workspace_id    uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            name            text NOT NULL,
            description     text NOT NULL DEFAULT '',
            identity        text NOT NULL DEFAULT '',
            rules           jsonb NOT NULL DEFAULT '[]',
            mcp_servers     jsonb NOT NULL DEFAULT '{}',
            tags            jsonb NOT NULL DEFAULT '[]',
            source          text NOT NULL DEFAULT 'inline',
            source_version  text NOT NULL DEFAULT '',
            enabled         boolean NOT NULL DEFAULT true,
            created_at      timestamptz NOT NULL DEFAULT now(),
            updated_at      timestamptz NOT NULL DEFAULT now(),

            UNIQUE (workspace_id, name)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS workspace_skills CASCADE")
    op.execute("DROP TABLE IF EXISTS workspace_templates CASCADE")
    op.execute("DROP TABLE IF EXISTS consolidation_log CASCADE")
    op.execute("DROP TABLE IF EXISTS daily_notes CASCADE")
    op.execute("DROP TABLE IF EXISTS memories CASCADE")
    op.execute("DROP TABLE IF EXISTS messages CASCADE")
    op.execute("DROP TABLE IF EXISTS sessions CASCADE")
    op.execute("DROP TABLE IF EXISTS workspaces CASCADE")
