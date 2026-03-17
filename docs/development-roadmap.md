# Development Roadmap

## Current Version: v0.6.0

## Completed Features

- [x] Core agent loop with iterative LLM + tool execution
- [x] Two-layer memory system (MEMORY.md + HISTORY.md)
- [x] 10 chat channel integrations (Telegram, Discord, WhatsApp, Feishu, Mochat, DingTalk, Slack, Email, QQ, Zalo)
- [x] 13+ LLM provider support via registry pattern
- [x] 7 built-in tool categories (shell, filesystem, web, message, spawn, cron, MCP)
- [x] MCP (Model Context Protocol) support — stdio + HTTP transports
- [x] Skills system with markdown-based dynamic loading
- [x] Subagent spawning for background tasks
- [x] Cron scheduling (expressions, intervals, one-time)
- [x] Session management with JSONL storage
- [x] Security hardening (shell guards, workspace restriction, allowFrom)
- [x] Docker deployment support
- [x] CLI with interactive mode + rich terminal UI
- [x] Voice transcription via Groq Whisper
- [x] Zalo media support (image/file sending via markers)
- [x] **Multi-tenant architecture** (workspaces, Postgres backend, Temporal orchestration)
- [x] **Three deployment modes** (Combined, Gateway, Worker)
- [x] **Kubernetes deployment** (Gateway deployment, Worker HPA, Ingress, ConfigMap, Secrets)
- [x] **Temporal-based durable workflows** (per-session workflows, per-bot task queues, Temporal Lite for dev)
- [x] **BASB 3-tier memory system** (Active/Reference/Archive with daily/weekly/monthly consolidation)
- [x] **LLM streaming responses** (token-by-token with debounced message updates)
- [x] **LLM retry with exponential backoff** (tenacity integration, transient error handling)
- [x] **OpenTelemetry observability** (tracing, metrics, cost tracking, Grafana/Jaeger export)
- [x] **Per-session tool locking** (concurrent message handling, 50+ sessions per worker)

## Planned Features

| Feature | Status | Priority |
|---------|--------|----------|
| Multi-modal support (images, voice, video) | In Progress | High |
| Long-term memory improvements | Planned | High |
| Multi-step planning and reflection | Planned | Medium |
| More integrations (Calendar, CRM) | Planned | Medium |
| Self-improvement from feedback | Planned | Low |
| Rate limiting | Planned | Medium |
| Cost tracking per provider | Planned | Low |
| Plugin/extension system | Planned | Low |

## Timeline

| Date | Milestone |
|------|-----------|
| 2026-02-02 | Initial launch |
| 2026-02-04 | Multi-provider + Docker support |
| 2026-02-05 | Feishu, DeepSeek, cron support |
| 2026-02-06 | Discord, Moonshot/Kimi, security hardening |
| 2026-02-08 | Provider registry refactor (2-step additions) |
| 2026-02-09 | Slack, Email, QQ support |
| 2026-02-11 | MiniMax support, CLI enhancements |
| 2026-02-12 | Memory system redesign |
| 2026-02-13 | v0.1.3.post7 release, security hardening |
| 2026-02-14 | MCP support |
| 2026-02-17 | Zalo media support (image/file markers) |
| 2026-02-22 | **Multi-tenant architecture (Combined/Gateway/Worker, Postgres, Temporal, K8s)** |
| 2026-02-22 | **CI/CD: Docker image publish pipeline, GHCR registry** |
| 2026-02-23 | **Multi-bot workspace architecture (bots.yaml, BotManager, per-bot identities/providers/skills)** |
| 2026-02-23 | **v0.6.0 release: Temporal workflows, BASB memory, streaming, observability** |
