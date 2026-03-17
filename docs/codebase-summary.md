# Codebase Summary

**Fork of:** [HKUDS/nanobot](https://github.com/HKUDS/nanobot) | **Generated:** 2026-02-22 | **Total Files:** 126 | **Total Tokens:** 123,084 | **Core LOC:** ~3,663

## Project Overview

**Miu-Bot** is an ultra-lightweight personal AI assistant built with Python 3.11+ with **multi-tenant architecture support**. It provides:

- **Async-first architecture** with event-driven message processing
- **Three deployment modes:** Combined (single-process), Gateway (message routing), Worker (task processing)
- **Multi-tenant support** via Postgres backend with workspace isolation
- **Task orchestration** via Temporal for durable distributed processing
- **10 chat channel integrations** (Telegram, Discord, WhatsApp, Feishu, Mochat, DingTalk, Slack, Email, QQ, Zalo)
- **13+ LLM provider support** via registry pattern (OpenAI, Anthropic, DeepSeek, Groq, Gemini, etc.)
- **7 built-in tool categories** (shell exec, filesystem, web search/fetch, messaging, spawning, cron scheduling, MCP)
- **Persistent memory system** with long-term facts and timestamped event logs
- **MemoryBackend protocol** with Postgres backend
- **MCP (Model Context Protocol) support** for extensible tool discovery
- **Markdown-based skills system** with frontmatter metadata
- **Session management** using append-only JSONL format
- **Security hardening** (shell guards, workspace restriction, allowFrom filtering)

## Directory Structure

```
miu_bot/
├── agent/               # Core agent logic (loop, context, memory, skills, tools)
│   ├── loop.py         # Main processing engine (~477 LOC)
│   ├── context.py      # Prompt assembly (~239 LOC)
│   ├── memory.py       # Persistent memory (~31 LOC)
│   ├── skills.py       # Skills loader (~229 LOC)
│   ├── subagent.py     # Background task spawning (~258 LOC)
│   └── tools/          # Tool implementations
├── channels/           # Chat platform integrations (one file per platform)
│   ├── base.py         # Channel interface
│   ├── manager.py      # Channel orchestration
│   ├── telegram.py, discord.py, whatsapp.py, ... (10 total)
├── bus/                # Message bus (async queues + event dataclasses)
│   ├── queue.py
│   └── events.py
├── providers/          # LLM provider abstraction (registry pattern)
│   ├── registry.py     # Provider specs and registry
│   ├── base.py         # LLM interface
│   ├── litellm_provider.py
│   └── transcription.py
├── config/             # Configuration schema (Pydantic) and loader
│   ├── schema.py       # DatabaseConfig, BackendConfig, TemporalConfig
│   └── loader.py
├── session/            # Conversation session storage (JSONL)
│   └── manager.py
├── cron/               # Scheduled task service
│   ├── service.py
│   └── types.py
├── gateway/            # FastAPI gateway (message routing)
│   ├── app.py
│   └── routes/
│       ├── admin.py    # Workspace CRUD endpoints
│       ├── health.py   # Health checks
│       └── internal.py # Internal APIs
├── dispatch/           # Temporal workflow orchestration
│   ├── client.py
│   ├── worker.py
│   ├── workflows.py
│   ├── activities.py
│   ├── schedules.py
│   └── gateway.py
├── worker/             # Worker mode (task processing, per-bot context)
│   ├── client.py
│   ├── response.py
│   └── workflows/
│       ├── process_message.py
│       ├── consolidate_memory.py
│       └── cron_task.py
├── memory/             # BASB 3-tier memory consolidation
│   ├── consolidation.py
│   ├── weekly.py
│   ├── monthly.py
│   ├── context_assembly.py
│   └── prompts.py
├── observability/      # OpenTelemetry tracing + metrics
│   ├── setup.py
│   ├── spans.py
│   ├── metrics.py
│   └── cost.py
├── workspace/          # Multi-tenant workspace management
│   ├── identity.py     # Workspace metadata
│   ├── config_merge.py # Config overrides
│   ├── service.py      # CRUD operations
│   └── resolver.py     # Channel→Workspace mapping
├── db/                 # Storage backend abstraction
│   ├── backend.py      # MemoryBackend protocol
│   ├── postgres.py     # PostgreSQL implementation
│   ├── import_legacy.py # Migration utility
│   ├── pool.py         # Connection pooling
│   ├── import_legacy.py # Migration utility
│   └── migrations/      # Alembic schema versions
├── skills/             # Bundled skills (markdown with frontmatter)
├── heartbeat/          # Proactive wake-up system
├── cli/                # CLI commands (Typer)
│   └── commands.py     # UPDATED: serve --role, workspace, db commands
└── utils/              # Shared helpers

bridge/                 # TypeScript WebSocket bridge (for Zalo/WhatsApp)
├── src/
│   ├── index.ts
│   ├── server.ts
│   ├── types.d.ts
│   └── whatsapp.ts
├── package.json
└── tsconfig.json

docs/                   # Project documentation
├── code-standards.md
├── system-architecture.md
├── development-roadmap.md
├── project-changelog.md
├── setup-telegram-guide.md
├── setup-zalo-guide.md
└── codebase-summary.md

tests/                  # Test suite
└── [unit and integration tests]
```

## Core Modules

### Agent Loop (`miu_bot/agent/loop.py`)

**Size:** ~477 LOC | **Responsibility:** Main processing engine

The heart of miu-bot. Receives `InboundMessage` from channels, builds context, iteratively calls the LLM with tool execution support, and sends responses back via `OutboundMessage`.

**Key Methods:**
- `process_message()` — Main message handling loop
- `_execute_tool()` — Execute a single tool and handle errors
- `_maybe_consolidate_memory()` — Trigger memory summarization when conversation exceeds `memory_window`

**Tool Loop:** Iterates up to 20 times, checking for `tool_calls` in LLM response. Each tool result is appended to messages for next iteration.

### Context Builder (`miu_bot/agent/context.py`)

**Size:** ~239 LOC | **Responsibility:** Prompt assembly

Assembles the system prompt from:
1. **Agent identity** (from `identity.md`)
2. **Long-term memory** (from `MEMORY.md`)
3. **Recent history** (from `HISTORY.md`)
4. **Loaded skills** (from `skills/` directory)
5. **Conversation history** (last N messages)
6. **Channel-specific instructions** (e.g., Zalo media markers)

Supports multimodal input (base64-encoded images in conversation).

### Memory System (`miu_bot/agent/memory.py`)

**Size:** ~31 LOC | **Responsibility:** Persistent memory management

Two-layer design:
- **MEMORY.md** — Long-term facts, user preferences, project context
- **HISTORY.md** — Timestamped event log, searchable summaries

Consolidation is triggered when session messages exceed `memory_window` (default: 50). The LLM summarizes old messages, extracts facts, and updates both files. Original session JSONL remains append-only.

### Skills Loader (`miu_bot/agent/skills.py`)

**Size:** ~229 LOC | **Responsibility:** Dynamic skill loading

Skills are markdown files with YAML frontmatter:

```markdown
---
description: What this skill does
always: false
metadata:
  requires:
    bins: ["git"]
    env: ["GITHUB_TOKEN"]
---

# Skill instructions here
```

Supports:
- **Always-on skills** — Loaded for every prompt
- **Progressive skills** — Loaded when needed (future: LLM decides)
- **Metadata validation** — Checks required binaries and env vars

### Subagent Manager (`miu_bot/agent/subagent.py`)

**Size:** ~258 LOC | **Responsibility:** Background task spawning

Spawns isolated agents with focused prompts and restricted tool sets. Each subagent:
- Runs in a background asyncio task
- Has max 15 iterations (prevents runaway)
- Can target specific channels or user groups
- Reports results back to parent via callback

## Tools (`miu_bot/agent/tools/`)

| Tool | File | Description |
|------|------|-------------|
| `exec` | `shell.py` | Shell execution with safety guards (blocks `rm -rf`, fork bombs). 60s timeout |
| `read_file` | `filesystem.py` | Read file contents |
| `write_file` | `filesystem.py` | Write/create files |
| `edit_file` | `filesystem.py` | Edit existing files |
| `list_dir` | `filesystem.py` | List directory contents |
| `web_search` | `web.py` | Search via Brave Search API |
| `web_fetch` | `web.py` | Extract content from URLs |
| `message` | `message.py` | Cross-channel messaging |
| `spawn` | `spawn.py` | Spawn subagents for background tasks |
| `cron` | `cron.py` | Schedule recurring/one-time tasks |
| `mcp_*` | `mcp.py` | MCP server tools (dynamically registered) |

## Channels (`miu_bot/channels/`)

All channels implement the same interface: `start()`, `stop()`, `send()`, `is_allowed()`, `_handle_message()`.

| Channel | Transport | Media | Public IP |
|---------|-----------|-------|-----------|
| **Telegram** | Long polling | Built-in | No |
| **Discord** | WebSocket gateway | Built-in | No |
| **WhatsApp** | Node.js bridge | Built-in | No |
| **Feishu** | WebSocket long connection | Built-in | No |
| **Mochat** | Socket.IO + msgpack | Built-in | No |
| **DingTalk** | Stream mode | Built-in | No |
| **Slack** | Socket mode | Built-in | No |
| **Email** | IMAP polling + SMTP | Attachments | No |
| **QQ** | botpy SDK | Built-in | No |
| **Zalo** | WebSocket bridge | Marker protocol | No |

### Gateway (`miu_bot/gateway/`)

FastAPI application for message routing and workspace management:
- **app.py** — FastAPI setup, route registration, startup/shutdown
- **routes/admin.py** — Workspace CRUD endpoints (POST/GET/PUT/DELETE)
- **routes/health.py** — K8s liveness/readiness probes
- **routes/internal.py** — Internal message dispatch API

Used in **Gateway mode** (`miubot serve --role gateway`).

### Dispatch (`miu_bot/dispatch/`)

Temporal-based durable workflow orchestration:
- **client.py** — Temporal client initialization and connection management
- **worker.py** — Temporal worker startup with task queue routing
- **workflows.py** — Workflow definitions (message, consolidate_memory, cron_task)
- **activities.py** — Activity implementations (thin wrappers around core logic)
- **schedules.py** — Temporal schedule definitions (consolidation + cron jobs)
- **gateway.py** — Gateway-side Temporal client for message dispatch

### Worker (`miu_bot/worker/`)

Worker mode for distributed task processing:
- **client.py** — Worker setup with per-bot context
- **response.py** — Unified response type for workflows
- **workflows/process_message.py** — Main workflow: InboundMessage → agent → OutboundMessage
- **workflows/consolidate_memory.py** — Memory summarization workflow
- **workflows/cron_task.py** — Scheduled job execution workflow

Used in **Worker mode** (`miubot serve --role worker`).

### Workspace (`miu_bot/workspace/`)

Multi-tenant workspace management:
- **identity.py** — Workspace metadata (id, name, owner, created_at, paused)
- **config_merge.py** — Merge workspace config overrides with global config
- **service.py** — WorkspaceService for CRUD (create, list, get, update, pause, delete)
- **resolver.py** — WorkspaceResolver maps (channel, user_id) → workspace_id

### Database (`miu_bot/db/`)

Storage backend abstraction and implementations:
- **backend.py** — MemoryBackend protocol (abstract interface)
- **postgres.py** — PostgreSQL implementation (async, connection pooling)
- **pool.py** — AsyncPool for connection management
- **import_legacy.py** — Migrate single-tenant JSONL to multi-tenant Postgres
- **migrations/** — Alembic migration versions for schema versioning

## Zalo Media Protocol

Zalo supports media sending via marker-based protocol:

```
[send-image:/path/to/image.jpg] or [send-image:https://example.com/image.png]
[send-file:/path/to/file.pdf] or [send-file:/path|Caption text]
```

The `zalo_media.py` module extracts markers, downloads URLs if needed, and dispatches to the bridge.

## Providers (`miu_bot/providers/`)

Registry-driven design. Adding a provider = 2 steps:
1. Add `ProviderSpec` to `PROVIDERS` list in `registry.py`
2. Add field to `ProvidersConfig` in `schema.py`

**Supported Providers:**
- OpenRouter, Anthropic, OpenAI, DeepSeek, Groq, Gemini, Zhipu, DashScope/Qwen, Moonshot/Kimi, MiniMax, AiHubMix, vLLM, Custom

Backend: **LiteLLM** (unified API).

## Configuration

Schema: `miu_bot/config/schema.py` (Pydantic models)

**File Location:** `~/.miu_bot/config.json`

**Structure (with multi-tenant options):**
```json
{
  "agents": {
    "defaults": {
      "model": "provider/model-name",
      "maxTokens": 4096,
      "temperature": 0.7,
      "memoryWindow": 50
    }
  },
  "providers": {
    "anthropic": { "apiKey": "sk-ant-..." },
    "openai": { "apiKey": "sk-..." }
  },
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "BOT_TOKEN",
      "allowFrom": ["USER_ID_1"]
    }
  },
  "database": {
    "url": "postgresql://user:pass@host:5432/miubot",
    "minPoolSize": 5,
    "maxPoolSize": 20
  },
  "backend": {
    "type": "postgres"
  },
  "temporal": {
    "serverUrl": "localhost:7233",
    "namespace": "default"
  },
  "tools": {
    "web": { "search": { "apiKey": "..." } },
    "restrictToWorkspace": false,
    "mcpServers": {}
  }
}
```

**New multi-tenant sections:**
- **database** — PostgreSQL connection settings (optional)
- **backend** — Storage backend: "postgres" (multi-tenant)
- **temporal** — Durable workflow orchestration (gateway/worker modes)

## Session Storage

**Format:** JSONL (append-only)

**Location:** `~/.miu_bot/sessions/{channel}:{user_id}.jsonl`

**One entry per line:**
```json
{"role": "user", "content": "Hello"}
{"role": "assistant", "content": "Hi there!"}
```

## Security Model

| Layer | Mechanism |
|-------|-----------|
| **Shell execution** | Blocks dangerous patterns (rm -rf, fork bombs). 60s timeout. Output truncation |
| **Access control** | `allowFrom` whitelist per channel. Empty = allow all |
| **File access** | Optional `restrictToWorkspace` confines tools to `~/.miu_bot/workspace/` |
| **API keys** | Stored in config.json (recommended 0600 permissions). Env var fallback |
| **MCP** | Stdio processes sandboxed by OS. HTTP endpoints require explicit config |

## Testing

- **Location:** `tests/` directory
- **Framework:** pytest with async support
- **Mocking:** External API calls (LLM, search, channels)
- **Coverage:** Aim for >80% on critical modules

## Release & Deployment

**Current Version:** v0.3.0 (2026-02-22)

**Docker:** Images published to GHCR at `ghcr.io/dataplanelabs/miu-bot` with tags:
- `{sha_short}` — Commit-specific
- `latest`, `main` — Branch tracking
- `{version}` — Semantic version

**Git History:** Cleaned with single initial commit + 19 project commits (squashed from HKUDS/nanobot fork)

## Technology Stack

| Category | Technology |
|----------|-----------|
| **Language** | Python 3.11+ |
| **CLI** | Typer |
| **Config** | Pydantic + pydantic-settings |
| **LLM** | LiteLLM (multi-provider) |
| **Async** | asyncio |
| **HTTP** | httpx |
| **WebSocket** | websockets, python-socketio |
| **Logging** | loguru |
| **Terminal UI** | Rich, prompt-toolkit |
| **JSON** | json-repair (robust LLM parsing) |
| **Cron** | croniter |
| **MCP** | mcp SDK |
| **Bridge** | TypeScript (Bun) |
| **Container Registry** | Harbor (Docker images) |
| **CI/CD** | GitHub Actions |
| **Orchestration** | Kubernetes + Temporal |

## Key Design Patterns

### Registry Pattern (Providers)

Single source of truth via `ProviderSpec` dataclass in `registry.py`. No if-elif chains.

### Tool Registry Pattern

Tools self-register with name, description, and JSON schema. Dynamic registration at runtime. MCP tools registered alongside built-in tools.

### Event-Driven Decoupling

Channels and agent communicate only through `MessageBus`:
- `InboundMessage` — from channel to agent
- `OutboundMessage` — from agent to channel

No direct imports between modules.

### Append-Only Sessions

JSONL format. One entry per line. Never modified — only appended. Memory consolidation reads but does not alter session files.

## Naming Conventions

| Element | Convention | Example |
|---------|-----------|---------|
| Files | snake_case | `litellm_provider.py` |
| Classes | PascalCase | `AgentLoop`, `ToolRegistry` |
| Functions/methods | snake_case | `_process_message()`, `build_prompt()` |
| Constants | UPPER_SNAKE | `MAX_ITERATIONS`, `PROVIDERS` |
| Config fields | camelCase (JSON) | `apiKey`, `allowFrom` |
| Pydantic fields | snake_case (Python) | `api_key`, `allow_from` |

## Largest Modules (by LOC)

1. `loop.py` — ~477 LOC (acceptable for main engine)
2. `context.py` — ~239 LOC
3. `subagent.py` — ~258 LOC
4. `skills.py` — ~229 LOC

## Quick Start

```bash
# Install
uv tool install miu-bot

# Initialize config
miubot onboard

# Configure (edit ~/.miu-bot/config.json with API keys, channels)
nano ~/.miu-bot/config.json

# Test locally
miubot agent -m "Hello"

# Start gateway (runs all enabled channels)
miubot gateway
```

## Useful Documentation

- [Code Standards](./code-standards.md) — Coding conventions, design patterns, testing
- [System Architecture](./system-architecture.md) — High-level diagrams and data flows
- [Development Roadmap](./development-roadmap.md) — Planned features and timeline
- [Project Changelog](./project-changelog.md) — Release history and notable changes
- [Setup Telegram](./setup-telegram-guide.md) — Deploy as Telegram bot
- [Setup Zalo](./setup-zalo-guide.md) — Connect via Zalo WebSocket bridge
