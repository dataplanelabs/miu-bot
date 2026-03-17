# Project Changelog

## v0.20.3 (2026-02-25)

**Fix Huly Duplicate Issues & Improve Temporal Observability**

**Agent Loop Hardening**
- Side-effect dedup cache prevents re-executing same tool+args within a single agent loop run
- Per-tool call cap (MAX_SAME_TOOL_CALLS=3) limits any tool name to 3 invocations per loop
- Prefix-based side-effect detection (create_, update_, delete_, send_, etc.) with MCP namespace stripping
- Read-only tools (list, get, search) unaffected by dedup/cap

**MCP Timeout Hardening**
- MCP tool timeout increased 120s → 300s (covers slow Huly/external MCP servers)
- Timeout error message changed to soft "may have succeeded" — prevents LLM retry storms
- Temporal activity timeout increased 5min → 10min (2x headroom over MCP timeout)
- Heartbeat timeout increased 60s → 120s

**Temporal Observability Enrichment**
- Enriched heartbeat data: model, usage, reasoning preview, tool args/result previews, status
- Added `get_current_trace` workflow query handler — returns accumulated trace events for last message
- Added `get_processing_state` workflow query handler — returns model, tools used, timing metadata
- Activity result trace stored in workflow state for post-mortem inspection via Temporal UI

**OTel Spans**
- Made `get_tracer()` dynamic accessor — always returns tracer from current provider
- Removed duplicate TracerProvider initialization (defers to `setup.py:init_otel()`)

## v0.6.0 (2026-02-23)

**Architecture Redesign: Temporal, BASB Memory, Streaming, Observability**

**Core Architecture**
- Replaced Hatchet with Temporal for durable workflow orchestration
- Per-session durable workflows with infinite loop and full event history (ContinueAsNew every 500 messages)
- Per-bot task queue routing with configurable `--bot-filter` flag for worker isolation
- Temporal Lite for dev, self-hosted OSS + dedicated CNPG for production

**Memory System Enhancement**
- Implemented BASB 3-tier memory (Active/Reference/Archive)
- Daily consolidation cron (2 AM per-workspace timezone) via Temporal schedules
- Weekly consolidation (Sunday 3 AM) promotes stable knowledge, compresses daily notes
- Monthly consolidation (1st of month 4 AM) generates deep summaries, archives old Reference memories
- New tables: daily_notes, consolidation_log; extended memories table with tier, priority, expires_at
- Per-workspace timezone support from day one
- Dropped APScheduler dependency — all scheduling via Temporal native schedules

**Streaming Responses**
- LLM streaming support via `chat_stream()` method in LiteLLMProvider
- Stream buffering with configurable debounce interval (default 1.5s)
- Channel message editing for smooth streaming UX (Telegram, Discord)
- Temporal query-based streaming state transport (zero extra HTTP endpoints)
- Tool execution pauses stream, resumes with new LLM call

**LLM Reliability**
- Added tenacity retry with exponential backoff (3 attempts, 2s-30s with jitter)
- Retries on transient errors: RateLimitError, APIConnectionError, ServiceUnavailableError, Timeout
- Fails fast on auth errors (no wasted retries)
- Per-provider configurable retry parameters

**Concurrency & Performance**
- Per-session tool locking (replaced global lock) — allows 50+ concurrent sessions per worker
- Gateway-to-Worker latency <100ms
- Fixed concurrent message processing in combined mode

**Observability (OpenTelemetry)**
- Full tracing from message_received to response_sent
- Custom metrics: messages.received, llm.latency_seconds, llm.tokens, tool.latency_seconds, consolidation.cost_usd
- Span instrumentation for: message receive, task enqueue, LLM calls, tool execution, memory consolidation
- Loguru integration with trace_id/span_id injection
- Cost estimation by model (token -> USD)
- OTLP exporter (gRPC/HTTP) to Grafana Alloy, Jaeger, or any OTLP backend
- Configurable sampling rate and export interval

**Infrastructure & Deployment**
- Docker-compose: replaced hatchet-lite with temporal + dedicated temporal-db
- Helm chart: Temporal server config, bot-filter support, CNPG manifest for Temporal storage
- Migration: feature flag `dispatch.backend` (Temporal vs Hatchet) during transition
- Combined mode now requires Temporal (consistent behavior across dev/staging/prod)

**Breaking Changes**
- Hatchet removed from optional dependencies
- `dispatch.backend: "hatchet"` no longer supported (requires `temporal`)
- Combined mode requires Temporal (temporal-lite available for local dev)
- APScheduler removed (Temporal schedules replace all cron scheduling)

**Dependencies Added**
- temporalio >=1.7.0
- tenacity >=8.2.0
- opentelemetry-sdk >=1.20.0
- opentelemetry-exporter-otlp >=1.20.0

**Dependencies Removed**
- hatchet-sdk
- APScheduler

## Unreleased

**Vision Fallback Routing (2026-02-27)**
- Added `vision_fallback_model` field to BotProviderConfig for flexible image handling
- Implemented `describe_images()` in media_resolver.py to convert images to text descriptions
- 3-path vision routing in process_message.py:
  - Path 1: Native vision models send images as base64 inline
  - Path 2: Non-vision models with fallback configured describe images via fallback model
  - Path 3: No vision or fallback strips images gracefully (text preserved)
- Image descriptions wrapped in `<image_description untrusted="true">` tags
- Fallback vision model uses same provider credentials as primary model

**Data Model Enhancements (2026-02-23)**
- E1: Migration 004 — Added FK CASCADE constraint on `consolidation_log.workspace_id` to prevent orphan records on workspace deletion
- E5: SeaweedFS Media Persistence — `MediaConfig` pydantic model + `media_store.py` boto3 utilities for S3-compatible object storage. Media refs stored in `messages.metadata["media"]` with keys, MIME types, and sizes. Supports 90-day TTL via SeaweedFS native headers.
- E5 Integration: Updated Telegram adapter + loop.py for media upload. Local file support maintained; SeaweedFS optional via config. Async-wrapped to avoid event loop stalls (asyncio.to_thread).
- E6a: Intermediate Chain Persistence — All assistant+tool messages from agent loop now saved to DB after multi-turn interactions. Supports debugging and auditing of tool execution chains.
- E6b: LLM Usage Tracking — Token counts (prompt/completion/total) accumulated per turn and stored in final assistant message metadata. Enables cost analytics and resource usage monitoring.

**Cron Job Scheduler for Multi-Target Delivery (2026-02-23)**
- YAML-driven job definitions in `bots.yaml` via `jobs:` field per bot
- Job configuration: schedule (cron expression), timezone, prompt, target channels (Telegram, Zalo, etc.)
- Temporal native schedules for job execution (replaces APScheduler job runner)
- CronTaskProcessor orchestrates job execution and multi-target delivery
- run_cron_activity integrates with dispatch/activities.py
- ensure_job_schedules() creates Temporal schedules from bots.yaml config
- Support for environment variable resolution (chat_id_env) for sensitive target IDs
- Per-job timezone support for accurate schedule execution

**Workspace Template Separation Refactor (2026-02-23)**
- New `workspace_templates` table for per-workspace template storage (soul, user, agents, heartbeat)
- New `workspace_skills` table replacing inline config with structured per-skill rows
- BotConfig now supports separated fields: soul, user, agents (alongside legacy identity for backward compatibility)
- Skills resolved from inline/local sources and stored in dedicated table (not config_overrides)
- Worker loads templates + skills from DB, with fallback to legacy identity if templates absent
- Helm chart values.yaml updated with new template format example
- Migration 003 adds both tables with proper indexes and unique constraints

**Multi-Bot Workspace Architecture (2026-02-23)**
- New `config/bots.py` — BotConfig schema for defining multiple bot instances with separate identities, providers, channels, skills
- `config/bots.py:load_bots()` — Load bot definitions from YAML, resolve *_env fields for channel tokens
- New `channels/bot_manager.py` — BotManager class orchestrates multiple channel instances per bot (keyed `{bot_name}:{channel_type}`)
- Channel registry dynamic loading — Channels instantiated on-demand via importlib
- Outbound dispatcher routing — Routes messages to correct bot's channel instance based on `msg.bot_name`
- New `skills/` module — Skills system with loader, merger, schema for skill.yaml files
- `skills/schema.py` — SkillRef, IdentityFragment, ToolRule, MCPServerConfig for per-skill configuration
- `skills/loader.py` — Load skill.yaml files with identity fragments, tool rules, MCP configs
- `skills/merger.py` — Merge global identity + per-skill fragments + tool rules + MCP servers
- Gateway `--bots-config` CLI flag — Load multi-bot workspace definitions at startup
- Gateway auto-creates workspaces from `bots.yaml` on startup (WorkspaceService integration)
- Worker per-workspace provider creation — Each workflow execution creates fresh LLM provider for workspace
- Worker per-workspace tools registry — MCP servers loaded per-bot from bots.yaml config
- Workspace context includes `bot_name` — All messages tagged with bot identity for worker processing
- Helm chart updated — ConfigMap now supports `bots.yaml` volume mount for multi-bot deployments

**Helm Chart + FluxCD GitOps Deployment (2026-02-22)**
- Created Helm chart at `charts/miu-bot/` — templates all K8s resources (namespace, configmap, gateway, worker, HPA)
- CI: Added `publish-chart` job to release workflow — OCI push to `oci://ghcr.io/dataplanelabs/charts/miu-bot`
- FluxCD manifests in infra repo: HelmRelease, SOPS secrets, Traefik ingress, Cilium network policies, image automation
- `existingSecret` pattern — secrets NOT in chart values, SOPS-encrypted in infra repo
- Chart version tied to app version (from git tag)

**Multi-Tenant Architecture & CI/CD Pipeline (Major Release)**
- New modules: `db/` (MemoryBackend protocol + Postgres/File impl), `workspace/` (CRUD), `gateway/` (FastAPI router), `worker/` (Hatchet orchestration)
- Three deployment modes:
  - **Combined** (`miubot serve --role combined`) — Single-process development
  - **Gateway** (`miubot serve --role gateway`) — Message routing, workspace resolver
  - **Worker** (`miubot serve --role worker`) — Task execution, Hatchet workflows
- Workspace management:
  - New CLI: `miubot workspace [create|list|config|pause|delete]`
  - WorkspaceService for multi-tenant CRUD
  - Workspace identity (name, owner, paused status)
  - Config override mechanism per workspace
- Storage backends:
  - MemoryBackend protocol (abstract interface)
  - PostgreSQL backend with connection pooling (asyncpg)
  - File backend for development (~/.miu-bot/workspaces/{ws_id}/)
  - Alembic migrations for schema versioning
- Task orchestration:
  - Hatchet integration for distributed workflows
  - `process_message`, `consolidate_memory`, `cron_task` workflows
  - Gateway dispatches to Hatchet queue
- Database CLI:
  - `miubot db migrate` — Run Alembic migrations
  - `miubot db import-legacy` — Migrate single-tenant to multi-tenant
  - `miubot db status` — Check migration state
- Configuration:
  - New config sections: `database`, `backend`, `hatchet`
  - Workspace config overrides in database
- Kubernetes manifests:
  - Gateway deployment + service + ingress
  - Worker deployment + HPA (auto-scaling)
  - ConfigMap for shared config
  - Secrets for credentials

**CI/CD & Deployment (2026-02-22)**
- Docker image publishing pipeline: `.github/workflows/release.yml` auto-bumps version, creates GitHub release, builds+pushes to GHCR
- Workflow dispatch support for manual version input
- Images tagged with: `{sha_short}`, `latest`, `main`, `{version}` at `ghcr.io/dataplanelabs/miu-bot`
- GitHub App integration (`munmiu`) for automated tag creation via org secrets
- Side effect: auto-created releases trigger PyPI publishing via existing `publish.yml`
- Docker build fixes:
  - Added `COPY bridge/ bridge/` to Dockerfile for hatch force-include
  - Removed `bridge/` from `.dockerignore`
- K8s deployment images updated to GHCR: `ghcr.io/dataplanelabs/miu-bot:latest`
- Version bumped: `0.2.0` → `0.3.0` in `pyproject.toml`
- Git history cleanup: squashed [HKUDS/nanobot](https://github.com/HKUDS/nanobot) fork history → single initial commit (20 clean commits total)
- Added `.env.example` to git (template only, no sensitive data)
- Updated `.gitignore`: added `.coverage`, `repomix-output.xml`

**Fork Attribution**
- miu-bot is a fork of [HKUDS/nanobot](https://github.com/HKUDS/nanobot), an open-source personal AI assistant framework
- Key architectural changes: PostgreSQL backend (replacing JSON storage), Temporal workflows for durable orchestration, multi-tenant workspace architecture, Kubernetes-native deployment with Helm charts, and OpenTelemetry observability
- Original nanobot credits preserved; enhancements made for production deployment and scalability

- Zalo media support — marker-based image/file sending via `[send-image:path]` and `[send-file:path]` conventions
- ZCA bridge handlers for media dispatch with URL download support
- System prompt enhancements for Zalo media education (extract_media_markers, send_media helpers)
- **Rebrand:** nanobot → miu-bot (package name, CLI command, config directory, environment prefix)
  - Package: `nanobot-ai` → `miu-bot`
  - CLI: `nanobot` → `miu-bot`
  - Config directory: `~/.nanobot/` → `~/.miu_bot/`
  - Environment prefix: `NANOBOT_*` → `MIUBOT_*`
  - GitHub repository: `dataplanelabs/miu-bot`
  - All documentation updated to reflect new branding

## v0.1.3.post7 (2026-02-13)

- Security hardening and multiple improvements
- Recommended upgrade for all users

## v0.1.3.post6 (2026-02-10)

- General improvements and bug fixes
- See [release notes](https://github.com/dataplanelabs/miu_bot/releases/tag/v0.1.3.post6)

## v0.1.3.post5 (2026-02-07)

- Added Qwen/DashScope provider support
- Several key improvements

## v0.1.3.post4 (2026-02-04)

- Multi-provider support via registry pattern
- Docker deployment support

## Notable Changes (by date)

| Date | Change |
|------|--------|
| 2026-02-23 | Data model enhancements — FK constraint (E1), SeaweedFS media persistence (E5), intermediate chain + usage tracking (E6a/E6b) |
| 2026-02-22 | Helm chart + FluxCD GitOps deployment, multi-bot workspace architecture |
| 2026-02-16 | Zalo channel integration — WebSocket bridge support |
| 2026-02-14 | MCP (Model Context Protocol) support — stdio + HTTP transports |
| 2026-02-13 | v0.1.3.post7 — security hardening |
| 2026-02-12 | Memory system redesign — less code, more reliable |
| 2026-02-11 | MiniMax provider + CLI UX enhancements |
| 2026-02-09 | Slack, Email, QQ channel integrations |
| 2026-02-08 | Provider registry refactor — adding providers now takes 2 steps |
| 2026-02-07 | v0.1.3.post5 — Qwen support |
| 2026-02-06 | Moonshot/Kimi provider, Discord channel, security hardening |
| 2026-02-05 | Feishu channel, DeepSeek provider, cron scheduling |
| 2026-02-04 | v0.1.3.post4 — multi-provider + Docker |
| 2026-02-03 | vLLM integration for local LLM support |
| 2026-02-02 | miu-bot initial launch |
